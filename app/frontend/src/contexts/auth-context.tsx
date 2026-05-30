// auth-context.tsx — AuthProvider + useAuth().
//
// Responsibilities:
//   1. Install a one-time global fetch interceptor that injects
//      `Authorization: Bearer <token>` on every request targeting the API
//      base (VITE_API_URL), and triggers logout on any 401 response.
//   2. Bootstrap auth on load: extract an OAuth token from the URL hash if
//      present, then validate the stored token via GET /auth/me.
//   3. Expose { user, status, login, register, logout, loginWithOAuth }.

import { API_BASE, authService } from '@/services/auth-service';
import { AuthStatus, User } from '@/types/auth';
import {
  createContext,
  ReactNode,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';

const TOKEN_KEY = 'auth_token';

function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* swallow */
  }
}

/** Pull an OAuth `access_token` out of `window.location.hash`, if present.
 *  Cleans the token fragment from the URL so it isn't left in history. */
function extractTokenFromHash(): string | null {
  const hash = window.location.hash;
  if (!hash || !hash.includes('access_token=')) return null;
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const token = params.get('access_token');
  if (token) {
    // Strip the hash without reloading or leaving a history entry.
    const clean = window.location.pathname + window.location.search;
    window.history.replaceState(null, '', clean || '/');
  }
  return token;
}

interface AuthContextValue {
  user: User | null;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    full_name?: string,
  ) => Promise<void>;
  logout: () => Promise<void>;
  loginWithOAuth: (provider: 'google' | 'github') => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');

  // `logout` is referenced by the interceptor (on 401). The interceptor is
  // installed once in an effect; a ref keeps it pointed at the latest impl
  // without re-installing.
  const logoutRef = useRef<() => void>(() => {});

  const applyLogout = () => {
    setToken(null);
    setUser(null);
    setStatus('anon');
  };
  logoutRef.current = applyLogout;

  // --- One-time global fetch interceptor -------------------------------
  useEffect(() => {
    const originalFetch = window.fetch.bind(window);

    const isApiUrl = (url: string): boolean => url.startsWith(API_BASE);
    const isAuthRoute = (url: string): boolean =>
      url.startsWith(`${API_BASE}/auth/`);

    window.fetch = async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ): Promise<Response> => {
      // Resolve the request URL across the (string | Request | URL) overloads.
      let url: string;
      if (typeof input === 'string') url = input;
      else if (input instanceof URL) url = input.toString();
      else url = input.url;

      // Only touch API requests; leave vite asset / same-origin fetches alone.
      // Skip /auth/* — those set their own headers via authService.
      if (isApiUrl(url) && !isAuthRoute(url)) {
        const token = getToken();
        if (token) {
          const headers = new Headers(
            init?.headers || (input instanceof Request ? input.headers : undefined),
          );
          headers.set('Authorization', `Bearer ${token}`);
          init = { ...init, headers };
        }
      }

      const res = await originalFetch(input, init);

      // On 401 from an API route, drop the session so the UI returns to login.
      if (res.status === 401 && isApiUrl(url) && !isAuthRoute(url)) {
        logoutRef.current();
      }
      return res;
    };

    return () => {
      window.fetch = originalFetch;
    };
  }, []);

  // --- On-load bootstrap: OAuth hash -> /auth/me -> authed | anon ------
  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      // (1) OAuth return: token in the URL fragment.
      const hashToken = extractTokenFromHash();
      if (hashToken) setToken(hashToken);

      // (2) Validate whatever token we now hold.
      const token = getToken();
      if (!token) {
        if (!cancelled) {
          setUser(null);
          setStatus('anon');
        }
        return;
      }

      try {
        const me = await authService.me(token);
        if (!cancelled) {
          setUser(me);
          setStatus('authed');
        }
      } catch {
        if (!cancelled) {
          setToken(null);
          setUser(null);
          setStatus('anon');
        }
      }
    };

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  // --- Actions ---------------------------------------------------------
  const login = async (email: string, password: string) => {
    const { access_token } = await authService.login(email, password);
    setToken(access_token);
    const me = await authService.me(access_token);
    setUser(me);
    setStatus('authed');
  };

  const register = async (
    email: string,
    password: string,
    full_name?: string,
  ) => {
    const { access_token } = await authService.register(
      email,
      password,
      full_name,
    );
    setToken(access_token);
    const me = await authService.me(access_token);
    setUser(me);
    setStatus('authed');
  };

  const logout = async () => {
    const token = getToken();
    applyLogout();
    if (token) await authService.logout(token); // best effort
  };

  const loginWithOAuth = (provider: 'google' | 'github') => {
    window.location.href = authService.oauthUrl(provider);
  };

  return (
    <AuthContext.Provider
      value={{ user, status, login, register, logout, loginWithOAuth }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
