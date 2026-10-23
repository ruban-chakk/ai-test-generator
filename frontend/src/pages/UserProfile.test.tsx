import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { updateUserSettings } from '../api';
import UserProfile from './UserProfile';

vi.mock('../api', () => ({
  updateCurrentUser: vi.fn(),
  updateUserSettings: vi.fn(),
}));

const user = {
  id: 'user-1',
  username: 'admin',
  email: 'admin@example.com',
  role: 'admin' as const,
  active: true,
  settings_json: { theme: 'light' as const, density: 'comfortable' as const, reduce_motion: false },
};

function renderProfile(path: string, onUserChange = vi.fn()) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/profile/*" element={<UserProfile user={user} onUserChange={onUserChange} />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('UserProfile', () => {
  it('uses the settings hub pattern and provides workspace back navigation', () => {
    renderProfile('/profile');

    expect(screen.getByRole('heading', { name: 'Profile & user settings' })).toBeInTheDocument();
    expect(screen.getByText('Profile').closest('a')).toHaveAttribute('href', '/profile/profile');
    expect(screen.getByText('Workspace preferences').closest('a')).toHaveAttribute('href', '/profile/preferences');
    expect(screen.getByText('Access').closest('a')).toHaveAttribute('href', '/profile/access');
    expect(screen.getByRole('link', { name: 'Back to workspace' })).toHaveAttribute('href', '/requirements');
  });

  it('opens one settings section and saves preferences', async () => {
    const onUserChange = vi.fn();
    vi.mocked(updateUserSettings).mockResolvedValue({
      ...user,
      settings_json: { theme: 'dark', density: 'comfortable', reduce_motion: false },
    });
    const browserUser = userEvent.setup();
    renderProfile('/profile/preferences', onUserChange);

    expect(screen.getByRole('heading', { name: 'Workspace preferences', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'All user settings' })).toHaveAttribute('href', '/profile');
    await browserUser.selectOptions(screen.getByLabelText('Theme'), 'dark');
    await browserUser.click(screen.getByRole('button', { name: 'Save preferences' }));

    await waitFor(() => expect(updateUserSettings).toHaveBeenCalledWith({
      theme: 'dark', density: 'comfortable', reduce_motion: false,
    }));
    expect(onUserChange).toHaveBeenCalled();
  });
});
