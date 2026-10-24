import { LoginPage } from './components/auth/login-page';
import { Layout } from './components/Layout';
import { Toaster } from './components/ui/sonner';
import { useAuth } from './contexts/auth-context';

export default function App() {
  const { status } = useAuth();

  if (status === 'loading') {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-background text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (status === 'anon') {
    return (
      <>
        <LoginPage />
        <Toaster />
      </>
    );
  }

  return (
    <>
      <Layout />
      <Toaster />
    </>
  );
}
