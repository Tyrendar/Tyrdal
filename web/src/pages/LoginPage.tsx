import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Form, Input, Segmented, Typography } from "antd";
import { useState } from "react";
import { ApiError } from "../api/client";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";

export default function LoginPage() {
  const { t, lang, setLang, error } = useI18n();
  const { login } = useAuth();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (v: { username: string; password: string }) => {
    setBusy(true);
    setErr(null);
    try {
      await login(v.username.trim(), v.password);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setErr(t("login.failed"));
      else if (e instanceof ApiError && e.code === "checker_not_allowed") setErr(t("login.checkerNotAllowed"));
      else setErr(error(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ minHeight: "100%", display: "grid", placeItems: "center", padding: 16, background: "linear-gradient(160deg, #0b3b38, #0f766e)" }}>
      <Card style={{ width: "100%", maxWidth: 380 }}>
        <div style={{ textAlign: "center", marginBottom: 16 }}>
          <img src="/favicon.svg" alt="" width={48} height={48} />
          <Typography.Title level={4} style={{ marginTop: 8 }}>{t("login.title")}</Typography.Title>
          <Segmented size="small" value={lang} onChange={(v) => setLang(v as "fa" | "en")}
            options={[{ label: "فارسی", value: "fa" }, { label: "English", value: "en" }]} />
        </div>
        {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item name="username" label={t("login.username")} rules={[{ required: true }]}>
            <Input prefix={<UserOutlined />} autoFocus autoComplete="username" dir="ltr" size="large" />
          </Form.Item>
          <Form.Item name="password" label={t("login.password")} rules={[{ required: true }]}>
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" dir="ltr" size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={busy}>{t("login.submit")}</Button>
        </Form>
      </Card>
    </div>
  );
}
