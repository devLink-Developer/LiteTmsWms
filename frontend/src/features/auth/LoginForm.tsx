import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import type { LoginPayload } from "../../types/session";

type LoginFormProps = {
  isSubmitting: boolean;
  onSubmit: (payload: LoginPayload) => Promise<void>;
};

const REMEMBERED_USERNAME_KEY = "litelogistic.rememberedUsername";

export function LoginForm({ isSubmitting, onSubmit }: LoginFormProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [rememberUsername, setRememberUsername] = useState(false);

  useEffect(() => {
    try {
      const rememberedUsername = window.localStorage.getItem(REMEMBERED_USERNAME_KEY);
      if (rememberedUsername) {
        setUsername(rememberedUsername);
        setRememberUsername(true);
      }
    } catch {
      setRememberUsername(false);
    }
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedUsername = username.trim().toLowerCase();

    try {
      if (rememberUsername && normalizedUsername) {
        window.localStorage.setItem(REMEMBERED_USERNAME_KEY, normalizedUsername);
      } else {
        window.localStorage.removeItem(REMEMBERED_USERNAME_KEY);
      }
    } catch {
      // Login must not depend on browser storage.
    }

    await onSubmit({ username: normalizedUsername, password });
  }

  return (
    <form className="space-y-[17px]" onSubmit={(event) => void handleSubmit(event)}>
      <div className="space-y-3">
        <label className="block text-sm font-semibold leading-none text-[#252d3a]" htmlFor="username">
          Usuario o correo <span className="text-[#c62828]">*</span>
        </label>
        <input
          autoComplete="username"
          className="h-11 w-full rounded-md border border-[#cfdbe7] bg-white px-3.5 text-base text-[#1f2937] outline-none transition placeholder:text-[#8da1b8] focus:border-[#155894] focus:ring-2 focus:ring-[#d7e8f8]"
          id="username"
          onChange={(event) => setUsername(event.target.value)}
          placeholder="usuario@empresa.com"
          required
          value={username}
        />
      </div>

      <div className="space-y-3">
        <label className="block text-sm font-semibold leading-none text-[#252d3a]" htmlFor="password">
          Contrasena <span className="text-[#c62828]">*</span>
        </label>
        <input
          autoComplete="current-password"
          className="h-11 w-full rounded-md border border-[#cfdbe7] bg-white px-3.5 text-base text-[#1f2937] outline-none transition placeholder:text-[#8da1b8] focus:border-[#155894] focus:ring-2 focus:ring-[#d7e8f8]"
          id="password"
          onChange={(event) => setPassword(event.target.value)}
          placeholder={"\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"}
          required
          type="password"
          value={password}
        />
      </div>

      <div className="flex items-center gap-2 pl-5 pt-[1px]">
        <input
          checked={rememberUsername}
          className="h-4 w-4 rounded border-[#cfdbe7] accent-[#0c4f86]"
          id="remember-username"
          onChange={(event) => setRememberUsername(event.target.checked)}
          type="checkbox"
        />
        <label className="text-xs font-medium leading-none text-[#202938]" htmlFor="remember-username">
          Recordar este usuario
        </label>
      </div>

      <button
        className="mt-[8px] flex h-[44px] w-full items-center justify-center gap-2 rounded-md bg-[#0c4f86] px-5 text-sm font-bold uppercase text-white transition hover:bg-[#073f6f] disabled:cursor-not-allowed disabled:bg-[#8da1b8]"
        disabled={isSubmitting}
        type="submit"
      >
        <span aria-hidden="true" className="login-submit-icon" />
        {isSubmitting ? "INGRESANDO..." : "INGRESAR"}
      </button>
    </form>
  );
}
