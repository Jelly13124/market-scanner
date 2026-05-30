// login-page.tsx — anonymous-state gate. Centered card with a
// login/register toggle, email+password (+optional name on register),
// inline error text, and OAuth buttons.

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useAuth } from '@/contexts/auth-context';
import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';

type Mode = 'login' | 'register';

export function LoginPage() {
  const { t } = useTranslation();
  const { login, register, loginWithOAuth } = useAuth();

  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const friendlyError = (e: unknown): string => {
    const status = (e as { status?: number })?.status;
    if (status === 401) return t('auth.errorInvalidCredentials', 'Invalid email or password.');
    if (status === 409) return t('auth.errorEmailTaken', 'That email is already registered.');
    if (status === 422) return t('auth.errorInvalidInput', 'Check your email and password (min 8 characters).');
    return (e as Error)?.message || t('auth.errorGeneric', 'Something went wrong. Please try again.');
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === 'login') {
        await login(email, password);
      } else {
        await register(email, password, fullName.trim() || undefined);
      }
      // On success the provider flips status -> 'authed' and this page unmounts.
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const toggleMode = () => {
    setMode((m) => (m === 'login' ? 'register' : 'login'));
    setError(null);
  };

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-1">
          <CardTitle className="text-xl">
            {mode === 'login'
              ? t('auth.signInTitle', 'Sign in')
              : t('auth.createAccountTitle', 'Create account')}
          </CardTitle>
          <CardDescription>
            {mode === 'login'
              ? t('auth.signInSubtitle', 'Sign in to your account to continue.')
              : t('auth.createAccountSubtitle', 'Create an account to get started.')}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={onSubmit} className="space-y-3">
            {mode === 'register' && (
              <div className="space-y-1">
                <label className="text-sm text-muted-foreground" htmlFor="auth-name">
                  {t('auth.fullNameLabel', 'Full name (optional)')}
                </label>
                <Input
                  id="auth-name"
                  type="text"
                  autoComplete="name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder={t('auth.fullNamePlaceholder', 'Jane Doe')}
                />
              </div>
            )}

            <div className="space-y-1">
              <label className="text-sm text-muted-foreground" htmlFor="auth-email">
                {t('auth.emailLabel', 'Email')}
              </label>
              <Input
                id="auth-email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t('auth.emailPlaceholder', 'you@example.com')}
              />
            </div>

            <div className="space-y-1">
              <label className="text-sm text-muted-foreground" htmlFor="auth-password">
                {t('auth.passwordLabel', 'Password')}
              </label>
              <Input
                id="auth-password"
                type="password"
                required
                minLength={8}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t('auth.passwordPlaceholder', '••••••••')}
              />
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}

            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting
                ? t('common.loading', 'Loading...')
                : mode === 'login'
                  ? t('auth.signInButton', 'Sign in')
                  : t('auth.createAccountButton', 'Create account')}
            </Button>
          </form>

          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            {t('common.or', 'or')}
            <span className="h-px flex-1 bg-border" />
          </div>

          <div className="space-y-2">
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={() => loginWithOAuth('google')}
            >
              {t('auth.continueWithGoogle', 'Continue with Google')}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={() => loginWithOAuth('github')}
            >
              {t('auth.continueWithGitHub', 'Continue with GitHub')}
            </Button>
          </div>

          <div className="text-center text-sm text-muted-foreground">
            {mode === 'login'
              ? t('auth.noAccountPrompt', "Don't have an account?")
              : t('auth.haveAccountPrompt', 'Already have an account?')}{' '}
            <button
              type="button"
              onClick={toggleMode}
              className="text-primary underline-offset-4 hover:underline"
            >
              {mode === 'login'
                ? t('auth.switchToRegister', 'Sign up')
                : t('auth.switchToLogin', 'Sign in')}
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
