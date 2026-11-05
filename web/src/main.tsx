import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import enUS from "antd/locale/en_US";
import faIR from "antd/locale/fa_IR";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";
import { I18nProvider, useI18n } from "./i18n";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 } },
});

function Themed() {
  const { dir, lang } = useI18n();
  return (
    <ConfigProvider
      direction={dir}
      locale={lang === "fa" ? faIR : enUS}
      theme={{
        token: {
          colorPrimary: "#0f766e",
          fontFamily: "Vazirmatn, system-ui, -apple-system, 'Segoe UI', sans-serif",
          borderRadius: 6,
        },
        components: { Layout: { siderBg: "#0b3b38", triggerBg: "#08302d" }, Menu: { darkItemBg: "#0b3b38", darkSubMenuItemBg: "#08302d" } },
      }}
    >
      <AntApp>
        <AuthProvider>
          <App />
        </AuthProvider>
      </AntApp>
    </ConfigProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <I18nProvider>
          <Themed />
        </I18nProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
