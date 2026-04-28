import type { WorkspaceContext } from "../api/workspace";

export type SessionUser = {
  username: string;
  email: string;
  displayName: string;
  alias: string;
};

export type SessionBootstrap = {
  authenticated: boolean;
  csrfToken: string;
  appName: "Lite Logistic";
  user: SessionUser | null;
  workspace: (WorkspaceContext & { employee?: Record<string, unknown> | null }) | null;
};

export type LoginPayload = {
  username: string;
  password: string;
};

export type LoginResponse = {
  success: true;
  redirectTo: string;
  session: SessionBootstrap;
};

