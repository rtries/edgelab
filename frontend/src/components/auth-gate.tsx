"use client";
/** Gates every route behind a session. /login renders on its own,
 * without the terminal chrome; everything else waits for the session
 * to resolve, then either shows the terminal shell or bounces to
 * /login. */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { Loading, Shell } from "@/components/ui";

export function AuthGate({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const isLoginPage = pathname === "/login";

  useEffect(() => {
    if (!loading && !session && !isLoginPage) {
      router.replace("/login");
    }
  }, [loading, session, isLoginPage, router]);

  if (isLoginPage) return <>{children}</>;

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loading label="checking session" />
      </div>
    );
  }

  if (!session) {
    // Redirect is in flight (see effect above); render nothing in the meantime.
    return null;
  }

  return <Shell>{children}</Shell>;
}
