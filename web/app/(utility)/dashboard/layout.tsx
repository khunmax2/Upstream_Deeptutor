import DashboardTabs from "@/components/dashboard/DashboardTabs";

/**
 * Shared chrome for the Dashboard's two pages (Overview and Learner Anima),
 * so switching between them never re-mounts the tab strip.
 */
export default function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 px-6 pt-4">
        <DashboardTabs />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}
