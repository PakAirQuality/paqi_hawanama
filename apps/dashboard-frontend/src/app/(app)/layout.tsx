import { MainLayout } from "@/components/layout/MainLayout";
import { AppProviders } from "@/components/AppProviders";
import { SelectionProvider } from "@/lib/selection";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppProviders>
      <SelectionProvider>
        <MainLayout>{children}</MainLayout>
      </SelectionProvider>
    </AppProviders>
  );
}