import React, { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import AppShell from "./components/layout/AppShell";
import { Spinner, ToastHost } from "./components/ui";

const Login = lazy(() => import("./pages/Login"));
const Chat = lazy(() => import("./pages/Chat"));
const Employees = lazy(() => import("./pages/Employees"));
const Skills = lazy(() => import("./pages/Skills"));
const Tasks = lazy(() => import("./pages/Tasks"));
const Files = lazy(() => import("./pages/Files"));

const Overview = lazy(() => import("./pages/admin/Overview"));
const Users = lazy(() => import("./pages/admin/Users"));
const PublicAgents = lazy(() => import("./pages/admin/PublicAgents"));
const DataSecurity = lazy(() => import("./pages/admin/DataSecurity"));
const Knowledge = lazy(() => import("./pages/admin/Knowledge"));
const Channels = lazy(() => import("./pages/admin/Channels"));
const Audit = lazy(() => import("./pages/admin/Audit"));

function Boot() {
  return (
    <div className="grid h-full place-items-center bg-surface-100">
      <div className="flex flex-col items-center gap-3">
        <div className="grid h-11 w-11 animate-pulse-soft place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-white">
          <span className="text-[18px] font-semibold">D</span>
        </div>
        <Spinner label="正在加载 DataClaw…" />
      </div>
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Boot />;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <>{children}</>;
}

function AdminOnly({ children }: { children: React.ReactNode }) {
  const { isAdmin } = useAuth();
  if (!isAdmin) return <Navigate to="/chat" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <ToastHost />
        <Suspense fallback={<Boot />}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              <Route index element={<Navigate to="/chat" replace />} />
              <Route path="/chat" element={<Chat />} />
              <Route path="/chat/:employeeId" element={<Chat />} />
              <Route path="/chat/:employeeId/:sessionId" element={<Chat />} />
              <Route path="/employees" element={<Employees />} />
              <Route path="/skills" element={<Skills />} />
              <Route path="/tasks" element={<Tasks />} />
              <Route path="/files" element={<Files />} />
              <Route
                path="/admin"
                element={
                  <AdminOnly>
                    <Overview />
                  </AdminOnly>
                }
              />
              <Route
                path="/admin/users"
                element={
                  <AdminOnly>
                    <Users />
                  </AdminOnly>
                }
              />
              <Route
                path="/admin/agents"
                element={
                  <AdminOnly>
                    <PublicAgents />
                  </AdminOnly>
                }
              />
              <Route
                path="/admin/data"
                element={
                  <AdminOnly>
                    <DataSecurity />
                  </AdminOnly>
                }
              />
              <Route
                path="/admin/knowledge"
                element={
                  <AdminOnly>
                    <Knowledge />
                  </AdminOnly>
                }
              />
              <Route
                path="/admin/channels"
                element={
                  <AdminOnly>
                    <Channels />
                  </AdminOnly>
                }
              />
              <Route
                path="/admin/audit"
                element={
                  <AdminOnly>
                    <Audit />
                  </AdminOnly>
                }
              />
              <Route path="*" element={<Navigate to="/chat" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  );
}
