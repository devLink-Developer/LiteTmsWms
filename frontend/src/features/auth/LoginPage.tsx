import { Navigate, useNavigate } from "react-router-dom";

import { useSessionStore } from "../../stores/useSessionStore";
import type { LoginPayload } from "../../types/session";
import { LoginForm } from "./LoginForm";

export function LoginPage() {
  const bootstrap = useSessionStore((state) => state.bootstrap);
  const clearError = useSessionStore((state) => state.clearError);
  const login = useSessionStore((state) => state.login);
  const status = useSessionStore((state) => state.status);
  const navigate = useNavigate();

  if (bootstrap?.authenticated) {
    return <Navigate replace to="/pedidos/entrega" />;
  }

  async function handleSubmit(payload: LoginPayload) {
    clearError();
    try {
      const response = await login(payload);
      navigate(response.redirectTo || "/pedidos/entrega", { replace: true });
    } catch {
      // The session store surfaces the error through the global toast viewport.
    }
  }

  return (
    <main className="flex min-h-[100svh] items-start justify-center bg-[#f3f6f9] px-4 py-[26px] text-[#1f2937]">
      <section className="w-full max-w-[388px] overflow-hidden rounded-lg border-t-[3px] border-t-[#0f5a99] bg-white px-[27px] pb-[26px] pt-[32px] shadow-[0_30px_72px_rgba(15,42,67,0.16)]">
        <div className="flex justify-center">
          <div aria-label="Lite Logistic" className="flex items-center gap-1">
            <span className="text-base font-semibold leading-none text-[#30343a]">Lite Logistic</span>
            <span aria-hidden="true" className="litelogistic-mark" />
          </div>
        </div>

        <div className="mt-[29px] flex justify-center">
          <div className="flex h-[58px] w-[58px] items-center justify-center rounded-md bg-[#073f6f] text-xl font-semibold leading-none text-white">
            LL
          </div>
        </div>

        <h1 className="mt-[25px] text-center text-3xl font-semibold leading-tight text-[#202938]">Ingresar</h1>

        <div className="mt-[20px]">
          <LoginForm isSubmitting={status === "loading"} onSubmit={handleSubmit} />
        </div>
      </section>
    </main>
  );
}
