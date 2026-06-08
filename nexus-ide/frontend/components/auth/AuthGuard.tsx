"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { isTokenValid } from "../../lib/auth";

const PUBLIC_PATHS = ["/login"];

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const isPublic = PUBLIC_PATHS.includes(pathname);
    const valid = isTokenValid();
    if (!isPublic && !valid) {
      router.replace("/login?expired=1");
    }
    setChecked(true);
  }, [pathname, router]);

  if (!checked) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-[#0b0b14]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#7c6afb] border-t-transparent" />
      </div>
    );
  }

  return <>{children}</>;
}
