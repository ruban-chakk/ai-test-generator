import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getSavedSearches, searchArtifacts } from '../api';
import SemanticSearchPage from './SemanticSearch';


vi.mock('../api', () => ({
  searchArtifacts: vi.fn(),
  getSavedSearches: vi.fn(),
  saveArtifactSearch: vi.fn(),
  recordSearchJudgment: vi.fn(),
}));

const project = {
  id: 'project-1',
  name: 'Identity',
  status: 'active',
  requirement_count: 3,
  test_case_count: 7,
};

describe('Search page', () => {
  beforeEach(() => {
    vi.mocked(getSavedSearches).mockResolvedValue([]);
  });
  it('runs hybrid search by default and displays ranking evidence', async () => {
    const user = userEvent.setup();
    vi.mocked(searchArtifacts).mockResolvedValue([
      {
        vector_id: 'test_case:case-1:v1',
        entity_type: 'test_case',
        entity_id: 'case-1',
        title: 'Reject expired reset token',
        text: 'Expired reset tokens cannot change credentials.',
        score: 0.91,
        search_mode: 'hybrid',
        semantic_score: 0.88,
        keyword_score: 0.76,
        matched_fields: ['title'],
        metadata: { requirement_id: 'requirement-1' },
      },
    ]);

    render(
      <MemoryRouter>
        <SemanticSearchPage selectedProject={project} />
      </MemoryRouter>,
    );

    expect(screen.getByRole('radio', { name: /Hybrid/ })).toBeChecked();
    await user.type(screen.getByRole('searchbox'), 'expired token');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchArtifacts).toHaveBeenCalledWith(
      'project-1',
      'expired token',
      'hybrid',
      undefined,
    ));
    expect(await screen.findByText('Reject expired reset token')).toBeInTheDocument();
    expect(screen.getByText('Semantic 88%')).toBeInTheDocument();
    expect(screen.getByText('Keyword 76%')).toBeInTheDocument();
    expect(screen.getByText('Matched title')).toBeInTheDocument();
  });

  it('supports keyword-only search with an artifact filter', async () => {
    const user = userEvent.setup();
    vi.mocked(searchArtifacts).mockResolvedValue([]);
    render(
      <MemoryRouter>
        <SemanticSearchPage selectedProject={project} />
      </MemoryRouter>,
    );

    await user.type(screen.getByRole('searchbox'), 'AUTH-401');
    await user.click(screen.getByRole('radio', { name: /Keyword/ }));
    await user.selectOptions(screen.getByLabelText('Artifact type'), 'requirement');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchArtifacts).toHaveBeenCalledWith(
      'project-1',
      'AUTH-401',
      'keyword',
      'requirement',
    ));
    expect(await screen.findByText(/No keyword results found/)).toBeInTheDocument();
  });

  it('selectively searches unapproved test cases', async () => {
    const user = userEvent.setup();
    vi.mocked(searchArtifacts).mockResolvedValue([]);
    render(
      <MemoryRouter>
        <SemanticSearchPage selectedProject={project} />
      </MemoryRouter>,
    );

    await user.type(screen.getByRole('searchbox'), 'checkout regression');
    await user.selectOptions(screen.getByLabelText('Artifact type'), 'test_case');
    await user.selectOptions(screen.getByLabelText('Test-case approval'), 'unapproved');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchArtifacts).toHaveBeenCalledWith(
      'project-1',
      'checkout regression',
      'hybrid',
      'test_case',
      0,
      '',
      undefined,
      'unapproved',
    ));
  });
});
