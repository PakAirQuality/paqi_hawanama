import { MainLayout } from "@/components/layout/MainLayout";
import { AppProviders } from "@/components/AppProviders";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppProviders>
      <MainLayout>{children}</MainLayout>
    </AppProviders>
  );
}