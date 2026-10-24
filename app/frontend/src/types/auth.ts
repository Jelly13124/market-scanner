// Auth types — Wave 7 (multi-tenant accounts).
// Shape mirrors the backend GET /auth/me response.

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  is_superuser: boolean;
  timezone: string;
}

export type AuthStatus = 'loading' | 'authed' | 'anon';
