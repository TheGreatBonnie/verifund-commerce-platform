"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  ClipboardCheck,
  FileCheck2,
  LayoutDashboard,
  Package,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";

const NAV: Array<{ href: string; label: string; icon: LucideIcon }> = [
  { href: "/seller/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/seller/agent", label: "Agent", icon: Bot },
  { href: "/seller/orders", label: "Orders", icon: Package },
  { href: "/seller/fulfillment", label: "Fulfillment", icon: ClipboardCheck },
  { href: "/seller/evidence", label: "Evidence", icon: FileCheck2 },
  { href: "/seller/payouts", label: "Payouts", icon: Wallet },
];

export function SellerNav() {
  const pathname = usePathname();
  return (
    <nav className="mm-seller-nav" aria-label="Seller workspace">
      <ul>
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            pathname === href ||
            (href !== "/seller/dashboard" && pathname.startsWith(`${href}/`));
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
