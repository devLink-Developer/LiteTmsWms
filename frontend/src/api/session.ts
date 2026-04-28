import { requestJson } from "./client";
import type { LoginPayload, LoginResponse, SessionBootstrap } from "../types/session";

export async function fetchSessionBootstrap(): Promise<SessionBootstrap> {
  return requestJson<SessionBootstrap>("/auth/api/session/");
}

export async function login(payload: LoginPayload): Promise<LoginResponse> {
  return requestJson<LoginResponse>("/auth/api/login/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function logout(): Promise<{ success: boolean; redirectTo: string }> {
  return requestJson<{ success: boolean; redirectTo: string }>("/auth/api/logout/", {
    method: "POST",
  });
}

