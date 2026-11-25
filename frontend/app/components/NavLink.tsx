"use client";

import NextLink from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/** A navigation link that marks itself as the current page (exact, or a section prefix). */
export function NavLink({
  href,
  className,
  section = false,
  children,
  title,
}: {
  href: string;
  className?: string;
  /** Also current on sub-pages (e.g. /courses for /courses/1001). */
  section?: boolean;
  children: ReactNode;
  title?: string;
}) {
  const pathname = usePathname() ?? "/";
  const current = pathname === href || (section && pathname.startsWith(`${href}/`));
  return (
    <NextLink href={href} className={className} aria-current={current ? "page" : undefined} title={title}>
      {children}
    </NextLink>
  );
}
