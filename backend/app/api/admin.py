import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import APP_ADMIN_ROLES, current_principal, hash_password, require_app_admin
from app.db import get_db
from app.models import (
    AIModelConfiguration,
    AIUsageRecord,
    AuditLog,
    Invitation,
    Organization,
    OrganizationMembership,
    Project,
    ProjectMembership,
    PromptConfiguration,
    PromptConfigurationVersion,
    User,
)
from app.schemas import (
    AICostSummary,
    AdminContext,
    AIModelConfigurationSummary,
    AIModelConfigurationUpdate,
    PromptConfigurationSummary,
    PromptConfigurationUpdate,
    PromptConfigurationVersionSummary,
    EffectivePromptConfigurationSummary,
    AdminUserCreate,
    AdminUserRoleUpdate,
    InvitationCreate,
    InvitationSummary,
    OrganizationCreate,
    OrganizationMembershipSummary,
    OrganizationMembershipUpsert,
    OrganizationSummary,
    UserSummary,
)
from app.services.prompts import DEFAULT_PROMPTS


admin_router = APIRouter(prefix="/admin", tags=["Administration"])
PROJECT_MEMBER_ROLES = {"reviewer", "tester", "test_lead", "product_manager", "approver", "project_admin"}


def _is_app_admin() -> bool:
    return current_principal().role in APP_ADMIN_ROLES


@admin_router.get("/context", response_model=AdminContext)
async def get_admin_context(db: AsyncSession = Depends(get_db)) -> AdminContext:
    principal = current_principal()
    organization_ids = list((await db.scalars(select(OrganizationMembership.organization_id).where(OrganizationMembership.user_id == principal.user_id, OrganizationMembership.role == "org_admin"))).all())
    project_ids = list((await db.scalars(select(ProjectMembership.project_id).where(ProjectMembership.user_id == principal.user_id, ProjectMembership.role.in_(["project_admin", "admin"])))).all())
    return AdminContext(is_app_admin=_is_app_admin(), organization_admin_ids=organization_ids, project_admin_ids=project_ids)


async def _organization_role(db: AsyncSession, organization_id: uuid.UUID) -> str | None:
    return await db.scalar(
        select(OrganizationMembership.role).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == current_principal().user_id,
        )
    )


async def _require_org_admin(db: AsyncSession, organization_id: uuid.UUID) -> None:
    if _is_app_admin():
        return
    if await _organization_role(db, organization_id) != "org_admin":
        raise HTTPException(status_code=403, detail="Organization administrator access required")


async def _require_project_admin(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if _is_app_admin() or await _organization_role(db, project.organization_id) == "org_admin":
        return project
    role = await db.scalar(
        select(ProjectMembership.role).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == current_principal().user_id,
        )
    )
    if role not in {"project_admin", "admin"}:
        raise HTTPException(status_code=403, detail="Project administrator access required")
    return project


@admin_router.get("/organizations", response_model=list[OrganizationSummary])
async def list_organizations(db: AsyncSession = Depends(get_db)) -> list[OrganizationSummary]:
    principal = current_principal()
    project_counts = select(Project.organization_id, func.count(Project.id).label("count")).group_by(Project.organization_id).subquery()
    member_counts = select(OrganizationMembership.organization_id, func.count(OrganizationMembership.id).label("count")).group_by(OrganizationMembership.organization_id).subquery()
    stmt = (
        select(Organization, func.coalesce(project_counts.c.count, 0), func.coalesce(member_counts.c.count, 0))
        .outerjoin(project_counts, project_counts.c.organization_id == Organization.id)
        .outerjoin(member_counts, member_counts.c.organization_id == Organization.id)
        .order_by(Organization.name)
    )
    if principal.role not in APP_ADMIN_ROLES:
        stmt = stmt.join(OrganizationMembership).where(OrganizationMembership.user_id == principal.user_id)
    rows = (await db.execute(stmt)).all()
    return [OrganizationSummary(id=org.id, name=org.name, slug=org.slug, status=org.status, project_count=projects, member_count=members, created_at=org.created_at) for org, projects, members in rows]


@admin_router.post("/organizations", response_model=OrganizationSummary)
async def create_organization(payload: OrganizationCreate, db: AsyncSession = Depends(get_db)) -> OrganizationSummary:
    principal = require_app_admin()
    if await db.scalar(select(Organization.id).where((func.lower(Organization.name) == payload.name.lower()) | (Organization.slug == payload.slug))):
        raise HTTPException(status_code=409, detail="Organization name or slug already exists")
    organization = Organization(name=payload.name.strip(), slug=payload.slug, status="active")
    db.add(organization)
    await db.flush()
    db.add(OrganizationMembership(organization_id=organization.id, user_id=principal.user_id, role="org_admin"))
    db.add(AuditLog(entity_type="organization", entity_id=organization.id, action="organization_created", actor=principal.username, details={"slug": organization.slug}))
    await db.commit()
    await db.refresh(organization)
    return OrganizationSummary(id=organization.id, name=organization.name, slug=organization.slug, status=organization.status, created_at=organization.created_at)


@admin_router.get("/organizations/{organization_id}/members", response_model=list[OrganizationMembershipSummary])
async def list_organization_members(organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[OrganizationMembershipSummary]:
    await _require_org_admin(db, organization_id)
    rows = (await db.execute(select(OrganizationMembership, User).join(User).where(OrganizationMembership.organization_id == organization_id).order_by(User.username))).all()
    return [OrganizationMembershipSummary(id=membership.id, organization_id=organization_id, user_id=user.id, username=user.username, email=user.email, role=membership.role, created_at=membership.created_at) for membership, user in rows]


@admin_router.put("/organizations/{organization_id}/members", response_model=OrganizationMembershipSummary)
async def upsert_organization_member(organization_id: uuid.UUID, payload: OrganizationMembershipUpsert, db: AsyncSession = Depends(get_db)) -> OrganizationMembershipSummary:
    await _require_org_admin(db, organization_id)
    user = await db.get(User, payload.user_id)
    if not user or not user.active:
        raise HTTPException(status_code=404, detail="User not found")
    membership = await db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id == organization_id, OrganizationMembership.user_id == user.id))
    old_value = {"user_id": str(user.id), "role": membership.role} if membership else None
    if membership:
        membership.role = payload.role
    else:
        membership = OrganizationMembership(organization_id=organization_id, user_id=user.id, role=payload.role)
        db.add(membership)
    await db.flush()
    db.add(AuditLog(entity_type="organization", entity_id=organization_id, action="organization_member_upserted", actor=current_principal().username, details={"user_id": str(user.id), "old_value": old_value, "new_value": {"user_id": str(user.id), "role": payload.role}}))
    await db.commit()
    await db.refresh(membership)
    return OrganizationMembershipSummary(id=membership.id, organization_id=organization_id, user_id=user.id, username=user.username, email=user.email, role=membership.role, created_at=membership.created_at)


@admin_router.get("/users", response_model=list[UserSummary])
async def list_users(organization_id: uuid.UUID | None = Query(None), project_id: uuid.UUID | None = Query(None), db: AsyncSession = Depends(get_db)) -> list[UserSummary]:
    if _is_app_admin():
        stmt = select(User)
    elif project_id:
        await _require_project_admin(db, project_id)
        stmt = select(User).join(ProjectMembership).where(ProjectMembership.project_id == project_id)
    elif organization_id:
        await _require_org_admin(db, organization_id)
        stmt = select(User).join(OrganizationMembership).where(OrganizationMembership.organization_id == organization_id)
    else:
        raise HTTPException(status_code=403, detail="A permitted organization or project scope is required")
    return [UserSummary.model_validate(user) for user in (await db.execute(stmt.order_by(User.username))).scalars().unique().all()]


@admin_router.post("/users", response_model=UserSummary)
async def create_user(payload: AdminUserCreate, db: AsyncSession = Depends(get_db)) -> UserSummary:
    principal = require_app_admin()
    if await db.scalar(select(User.id).where((func.lower(User.username) == payload.username.lower()) | (func.lower(User.email) == payload.email.lower()))):
        raise HTTPException(status_code=409, detail="Username or email already exists")
    user = User(username=payload.username.strip(), email=payload.email.strip().lower(), role=payload.role, password_hash=hash_password(payload.password), active=True)
    db.add(user)
    await db.flush()
    db.add(AuditLog(entity_type="user", entity_id=user.id, action="user_created", actor=principal.username, details={"role": user.role}))
    await db.commit()
    await db.refresh(user)
    return UserSummary.model_validate(user)


@admin_router.patch("/users/{user_id}/role", response_model=UserSummary)
async def update_user_role(user_id: uuid.UUID, payload: AdminUserRoleUpdate, db: AsyncSession = Depends(get_db)) -> UserSummary:
    principal = require_app_admin()
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == principal.user_id and (payload.role != "app_admin" or not payload.active):
        raise HTTPException(status_code=409, detail="App administrators cannot remove their own active app-admin access")
    old_value = {"role": user.role, "active": user.active}
    user.role = payload.role
    user.active = payload.active
    user.token_version += 1
    db.add(AuditLog(entity_type="user", entity_id=user.id, action="user_role_updated", actor=principal.username, details={"old_value": old_value, "new_value": {"role": user.role, "active": user.active}}))
    await db.commit()
    await db.refresh(user)
    return UserSummary.model_validate(user)


@admin_router.post("/invitations", response_model=InvitationSummary)
async def create_invitation(payload: InvitationCreate, db: AsyncSession = Depends(get_db)) -> InvitationSummary:
    organization = await db.get(Organization, payload.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    if payload.project_id:
        if payload.project_role not in PROJECT_MEMBER_ROLES:
            raise HTTPException(status_code=422, detail="A supported project role is required")
        project = await _require_project_admin(db, payload.project_id)
        if project.organization_id != payload.organization_id:
            raise HTTPException(status_code=422, detail="Project does not belong to the organization")
        if not _is_app_admin() and await _organization_role(db, payload.organization_id) != "org_admin" and payload.organization_role != "member":
            raise HTTPException(status_code=403, detail="Project administrators cannot grant organization-admin access")
    else:
        await _require_org_admin(db, payload.organization_id)
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(
        organization_id=payload.organization_id,
        project_id=payload.project_id,
        email=payload.email.strip().lower(),
        organization_role=payload.organization_role,
        project_role=payload.project_role,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        invited_by=current_principal().user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days),
    )
    db.add(invitation)
    await db.flush()
    db.add(AuditLog(entity_type="invitation", entity_id=invitation.id, action="invitation_created", actor=current_principal().username, details={"organization_id": str(payload.organization_id), "project_id": str(payload.project_id) if payload.project_id else None, "email": invitation.email}))
    await db.commit()
    await db.refresh(invitation)
    return InvitationSummary.model_validate(invitation).model_copy(update={"invitation_token": raw_token})


async def _authorize_scope(db: AsyncSession, scope_type: str, scope_id: uuid.UUID | None) -> None:
    if scope_type == "app":
        require_app_admin()
    elif scope_type == "organization" and scope_id:
        await _require_org_admin(db, scope_id)
    elif scope_type == "project" and scope_id:
        await _require_project_admin(db, scope_id)
    else:
        raise HTTPException(status_code=422, detail="Invalid configuration scope")


@admin_router.get("/model-config/{scope_type}", response_model=AIModelConfigurationSummary | None)
async def get_model_configuration(scope_type: str, scope_id: uuid.UUID | None = Query(None), db: AsyncSession = Depends(get_db)):
    await _authorize_scope(db, scope_type, scope_id)
    return await db.scalar(select(AIModelConfiguration).where(AIModelConfiguration.scope_type == scope_type, AIModelConfiguration.scope_id.is_(None) if scope_id is None else AIModelConfiguration.scope_id == scope_id))


@admin_router.put("/model-config/{scope_type}", response_model=AIModelConfigurationSummary)
async def put_model_configuration(scope_type: str, payload: AIModelConfigurationUpdate, scope_id: uuid.UUID | None = Query(None), db: AsyncSession = Depends(get_db)):
    await _authorize_scope(db, scope_type, scope_id)
    config = await db.scalar(select(AIModelConfiguration).where(AIModelConfiguration.scope_type == scope_type, AIModelConfiguration.scope_id.is_(None) if scope_id is None else AIModelConfiguration.scope_id == scope_id))
    values = payload.model_dump()
    old_values = {key: getattr(config, key) for key in values} if config else None
    if config:
        for key, value in values.items():
            setattr(config, key, value)
        config.updated_by = current_principal().user_id
    else:
        config = AIModelConfiguration(scope_type=scope_type, scope_id=scope_id, updated_by=current_principal().user_id, **values)
        db.add(config)
    await db.flush()
    db.add(AuditLog(
        entity_type="ai_model_configuration",
        entity_id=config.id,
        action="model_configuration_updated",
        actor=current_principal().username,
        details={
            "scope_type": scope_type,
            "scope_id": str(scope_id) if scope_id else None,
            "old_value": jsonable_encoder(old_values),
            "new_value": jsonable_encoder({key: getattr(config, key) for key in values}),
        },
    ))
    await db.commit()
    await db.refresh(config)
    return config


async def _snapshot_prompt_version(db: AsyncSession, config: PromptConfiguration) -> None:
    existing = await db.scalar(select(PromptConfigurationVersion.id).where(
        PromptConfigurationVersion.prompt_configuration_id == config.id,
        PromptConfigurationVersion.version == config.version,
    ))
    if existing:
        return
    db.add(PromptConfigurationVersion(
        prompt_configuration_id=config.id,
        prompt_key=config.prompt_key,
        scope_type=config.scope_type,
        scope_id=config.scope_id,
        version=config.version,
        system_template=config.system_template,
        user_template=config.user_template,
        variables=config.variables or [],
        temperature=config.temperature,
        change_notes=config.change_notes,
        status=config.status,
        content_checksum=config.content_checksum,
        parent_configuration_id=config.parent_configuration_id,
        parent_version=config.parent_version,
        created_by=config.created_by,
        approved_by=config.approved_by,
        published_at=config.published_at,
    ))


async def _effective_prompt_configuration(
    db: AsyncSession,
    prompt_key: str,
    project_id: uuid.UUID,
    target_scope: str = "project",
) -> PromptConfiguration | None:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    scopes = {
        "project": (("project", project.id), ("organization", project.organization_id), ("app", None)),
        "organization": (("organization", project.organization_id), ("app", None)),
        "app": (("app", None),),
    }.get(target_scope)
    if scopes is None:
        raise HTTPException(status_code=422, detail="Unsupported effective prompt scope")
    for scope_type, scope_id in scopes:
        config = await db.scalar(select(PromptConfiguration).where(
            PromptConfiguration.prompt_key == prompt_key,
            PromptConfiguration.scope_type == scope_type,
            PromptConfiguration.status == "published",
            PromptConfiguration.scope_id.is_(None) if scope_id is None else PromptConfiguration.scope_id == scope_id,
        ))
        if config:
            return config
    return None


@admin_router.get("/prompt-config/{prompt_key}/effective", response_model=EffectivePromptConfigurationSummary)
async def get_effective_prompt_configuration(
    prompt_key: str,
    project_id: uuid.UUID,
    target_scope: str = Query("project"),
    db: AsyncSession = Depends(get_db),
) -> EffectivePromptConfigurationSummary:
    await _require_project_admin(db, project_id)
    if prompt_key not in DEFAULT_PROMPTS:
        raise HTTPException(status_code=422, detail="Unsupported prompt key")
    config = await _effective_prompt_configuration(db, prompt_key, project_id, target_scope)
    if config:
        return EffectivePromptConfigurationSummary(
            **{column.name: getattr(config, column.name) for column in PromptConfiguration.__table__.columns},
            effective_scope_type=config.scope_type,
            effective_scope_id=config.scope_id,
            inherited=config.scope_type != target_scope,
        )
    default = DEFAULT_PROMPTS[prompt_key]
    checksum = hashlib.sha256(f"{default.system_template}\n{default.user_template}\n{','.join(default.variables)}".encode("utf-8")).hexdigest()
    epoch = datetime(1970, 1, 1)
    return EffectivePromptConfigurationSummary(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"builtin-prompt:{prompt_key}"),
        prompt_key=prompt_key,
        system_template=default.system_template,
        user_template=default.user_template,
        variables=list(default.variables),
        temperature=default.temperature,
        change_notes="Built-in fallback",
        status="published",
        scope_type="built_in",
        scope_id=None,
        version=0,
        content_checksum=checksum,
        parent_configuration_id=None,
        parent_version=None,
        created_by=uuid.UUID(int=0),
        approved_by=None,
        published_at=epoch,
        updated_by=uuid.UUID(int=0),
        created_at=epoch,
        updated_at=epoch,
        effective_scope_type="built_in",
        effective_scope_id=None,
        inherited=True,
    )


@admin_router.get("/prompt-config/{prompt_key}/history", response_model=list[PromptConfigurationVersionSummary])
async def list_prompt_configuration_history(
    prompt_key: str,
    scope_type: str,
    scope_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[PromptConfigurationVersionSummary]:
    await _authorize_scope(db, scope_type, scope_id)
    return list((await db.scalars(select(PromptConfigurationVersion).where(
        PromptConfigurationVersion.prompt_key == prompt_key,
        PromptConfigurationVersion.scope_type == scope_type,
        PromptConfigurationVersion.scope_id.is_(None) if scope_id is None else PromptConfigurationVersion.scope_id == scope_id,
    ).order_by(PromptConfigurationVersion.version.desc(), PromptConfigurationVersion.created_at.desc()))).all())


@admin_router.get("/prompt-config/{prompt_key}", response_model=PromptConfigurationSummary | None)
async def get_prompt_configuration(
    prompt_key: str,
    scope_type: str,
    scope_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PromptConfigurationSummary | None:
    await _authorize_scope(db, scope_type, scope_id)
    return await db.scalar(select(PromptConfiguration).where(
        PromptConfiguration.prompt_key == prompt_key,
        PromptConfiguration.scope_type == scope_type,
        PromptConfiguration.scope_id.is_(None) if scope_id is None else PromptConfiguration.scope_id == scope_id,
    ))


@admin_router.put("/prompt-config/{prompt_key}", response_model=PromptConfigurationSummary)
async def put_prompt_configuration(
    prompt_key: str,
    payload: PromptConfigurationUpdate,
    scope_type: str,
    scope_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PromptConfigurationSummary:
    await _authorize_scope(db, scope_type, scope_id)
    if payload.prompt_key != prompt_key:
        raise HTTPException(status_code=422, detail="Prompt key does not match the URL")
    import re
    placeholders = set(re.findall(r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}", payload.system_template + "\n" + payload.user_template))
    if not placeholders.issubset(set(payload.variables)):
        missing = ", ".join(sorted(placeholders - set(payload.variables)))
        raise HTTPException(status_code=422, detail=f"Prompt variables must declare: {missing}")
    checksum = hashlib.sha256(
        f"{payload.system_template}\n{payload.user_template}\n{','.join(payload.variables)}".encode("utf-8")
    ).hexdigest()
    parent = None
    if scope_type == "organization":
        parent = await db.scalar(select(PromptConfiguration).where(
            PromptConfiguration.prompt_key == prompt_key,
            PromptConfiguration.scope_type == "app",
            PromptConfiguration.scope_id.is_(None),
            PromptConfiguration.status == "published",
        ))
    elif scope_type == "project" and scope_id:
        project = await db.get(Project, scope_id)
        if project:
            parent = await db.scalar(select(PromptConfiguration).where(
                PromptConfiguration.prompt_key == prompt_key,
                PromptConfiguration.scope_type == "organization",
                PromptConfiguration.scope_id == project.organization_id,
                PromptConfiguration.status == "published",
            ))
            if not parent:
                parent = await db.scalar(select(PromptConfiguration).where(
                    PromptConfiguration.prompt_key == prompt_key,
                    PromptConfiguration.scope_type == "app",
                    PromptConfiguration.scope_id.is_(None),
                    PromptConfiguration.status == "published",
                ))
    config = await db.scalar(select(PromptConfiguration).where(
        PromptConfiguration.prompt_key == prompt_key,
        PromptConfiguration.scope_type == scope_type,
        PromptConfiguration.scope_id.is_(None) if scope_id is None else PromptConfiguration.scope_id == scope_id,
    ))
    values = payload.model_dump(exclude={"prompt_key"})
    old_values = (
        {
            key: getattr(config, key)
            for key in (
                "system_template", "user_template", "variables", "temperature", "change_notes",
                "version", "status", "content_checksum", "parent_configuration_id", "parent_version",
                "approved_by", "published_at",
            )
        }
        if config else None
    )
    if config:
        await _snapshot_prompt_version(db, config)
        config.version += 1
        for key, value in values.items():
            setattr(config, key, value)
        config.content_checksum = checksum
        config.parent_configuration_id = parent.id if parent else None
        config.parent_version = parent.version if parent else None
        config.approved_by = current_principal().user_id if payload.status == "published" else None
        config.published_at = datetime.now(timezone.utc).replace(tzinfo=None) if payload.status == "published" else None
        config.updated_by = current_principal().user_id
    else:
        config = PromptConfiguration(
            scope_type=scope_type,
            scope_id=scope_id,
            prompt_key=prompt_key,
            created_by=current_principal().user_id,
            updated_by=current_principal().user_id,
            content_checksum=checksum,
            parent_configuration_id=parent.id if parent else None,
            parent_version=parent.version if parent else None,
            approved_by=current_principal().user_id if payload.status == "published" else None,
            published_at=datetime.now(timezone.utc).replace(tzinfo=None) if payload.status == "published" else None,
            **values,
        )
        db.add(config)
    await db.flush()
    await _snapshot_prompt_version(db, config)
    db.add(AuditLog(
        entity_type="prompt_configuration",
        entity_id=config.id,
        action="prompt_configuration_updated",
        actor=current_principal().username,
        details={
            "prompt_key": prompt_key,
            "scope_type": scope_type,
            "scope_id": str(scope_id) if scope_id else None,
            "version": config.version,
            "old_value": jsonable_encoder(old_values),
            "new_value": jsonable_encoder({
                key: getattr(config, key)
                for key in (
                    "system_template", "user_template", "variables", "temperature", "change_notes",
                    "version", "status", "content_checksum", "parent_configuration_id", "parent_version",
                    "approved_by", "published_at",
                )
            }),
        },
    ))
    await db.commit()
    await db.refresh(config)
    return config


@admin_router.get("/costs/{scope_type}/{scope_id}", response_model=AICostSummary)
async def get_cost_summary(scope_type: str, scope_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> AICostSummary:
    if scope_type == "organization":
        await _require_org_admin(db, scope_id)
        scope_filter = AIUsageRecord.organization_id == scope_id
    elif scope_type == "project":
        await _require_project_admin(db, scope_id)
        scope_filter = AIUsageRecord.project_id == scope_id
    else:
        raise HTTPException(status_code=422, detail="Cost scope must be organization or project")
    totals = (await db.execute(select(func.coalesce(func.sum(AIUsageRecord.cost_micros), 0), func.coalesce(func.sum(AIUsageRecord.input_tokens), 0), func.coalesce(func.sum(AIUsageRecord.output_tokens), 0)).where(scope_filter))).one()
    project_rows = (await db.execute(select(AIUsageRecord.project_id, func.sum(AIUsageRecord.cost_micros), func.sum(AIUsageRecord.input_tokens + AIUsageRecord.output_tokens)).where(scope_filter).group_by(AIUsageRecord.project_id))).all()
    model_rows = (await db.execute(
        select(
            AIUsageRecord.model,
            func.sum(AIUsageRecord.cost_micros),
            func.sum(AIUsageRecord.input_tokens),
            func.sum(AIUsageRecord.output_tokens),
            func.array_agg(func.distinct(AIUsageRecord.pricing_source)),
        ).where(scope_filter).group_by(AIUsageRecord.model)
    )).all()
    unpriced_models = list((await db.scalars(
        select(AIUsageRecord.model).where(
            scope_filter,
            AIUsageRecord.pricing_source == "unpriced",
            AIUsageRecord.input_tokens + AIUsageRecord.output_tokens > 0,
        ).distinct()
    )).all())
    return AICostSummary(
        scope_type=scope_type,
        scope_id=scope_id,
        total_cost_micros=totals[0],
        total_input_tokens=totals[1],
        total_output_tokens=totals[2],
        by_project=[{"project_id": str(row[0]), "cost_micros": row[1], "tokens": row[2]} for row in project_rows],
        by_model=[{
            "model": row[0],
            "cost_micros": row[1],
            "input_tokens": row[2],
            "output_tokens": row[3],
            "tokens": row[2] + row[3],
            "pricing_sources": row[4] or [],
        } for row in model_rows],
        unpriced_models=unpriced_models,
    )
