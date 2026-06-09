export type RequirementSummary = {
  id: string;
  external_id?: string;
  title: string;
  description?: string;
  source: string;
  status: string;
  created_at?: string;
  updated_at?: string;
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

export async function getRequirements(): Promise<RequirementSummary[]> {
  const response = await fetch(`${API_BASE_URL}/requirements`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch requirements: ${response.statusText}`);
  }

  return response.json();
}
