"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ClipboardList,
  FileClock,
  LayoutDashboard,
  ListChecks,
  Settings,
  ShieldCheck,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";

const NAV: Array<{ href: string; label: string; icon: LucideIcon }> = [
  { href: "/admin", label: "Overview", icon: LayoutDashboard },
  { href: "/admin/transactions", label: "Platform transactions", icon: ClipboardList },
  { href: "/admin/payouts", label: "Payouts", icon: Wallet },
  { href: "/admin/disputes", label: "Disputes", icon: ListChecks },
  { href: "/admin/verification", label: "Verification", icon: ShieldCheck },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/audit", label: "Audit", icon: FileClock },
  { href: "/admin/settings", label: "Settings", icon: Settings },
];

export function AdminNav() {
  const pathname = usePathname();
  return (
    <nav className="mm-seller-nav" aria-label="Admin workspace">
      <ul>
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            pathname === href ||
            (href !== "/admin" && pathname.startsWith(`${href}/`));
          return (
            <li key={href}>
              <Link
                href={href}
                className={cn("mm-seller-nav-link", active && "is-active")}
                aria-current={active ? "page" : undefined}
              >
                <Icon size={15} aria-hidden="true" />
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
