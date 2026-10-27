import { ConsoleLayout } from "@/components/layout/console-layout";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <ConsoleLayout>{children}</ConsoleLayout>;
}
