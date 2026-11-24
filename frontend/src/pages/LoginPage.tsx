import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { ApiError } from "@/api/client";
import { queryKeys, useLogin } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConfig } from "@/lib/config-context";
import { safeNext } from "@/lib/navigation";
import { hasForbiddenCharacters } from "@/lib/text";

// Mirrors the backend's LoginRequest limits; the server stays authoritative.
const LoginSchema = z.object({
  username: z
    .string()
    .min(1, "Enter your username.")
    .max(150, "Username is too long.")
    .refine((value) => !hasForbiddenCharacters(value), "Username contains invalid characters."),
  password: z.string().min(1, "Enter your password.").max(1024, "Password is too long."),
});
type LoginValues = z.infer<typeof LoginSchema>;

export function LoginPage() {
  const config = useConfig();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const login = useLogin();
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<LoginValues>({
    resolver: zodResolver(LoginSchema),
    defaultValues: { username: "", password: "" },
  });
  const { errors, isSubmitting } = form.formState;
  // Already signed in (e.g. a bookmarked login link): go where `next` points.
  // A sign-out lands here before the cache is cleared: never bounce it back.
  const location = useLocation();
  const queryClient = useQueryClient();
  const signingOut = (location.state as { signedOut?: unknown } | null)?.signedOut === true;
  const signedIn = !signingOut && queryClient.getQueryData(queryKeys.me) !== undefined;

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login.mutateAsync(values);
      void navigate(safeNext(params.get("next")), { replace: true });
    } catch (error) {
      form.resetField("password");
      setFormError(error instanceof ApiError ? error.message : "Sign-in failed.");
    }
  });

  if (signedIn && !isSubmitting) {
    return <Navigate to={safeNext(params.get("next"))} replace />;
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle as="h1">{config.title}</CardTitle>
          <p className="text-sm text-muted-foreground">Sign in to continue.</p>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => void onSubmit(event)}
            noValidate
          >
            {formError !== null && (
              <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {formError}
              </p>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                autoComplete="username"
                autoFocus
                aria-invalid={errors.username ? true : undefined}
                aria-describedby={errors.username ? "username-error" : undefined}
                {...form.register("username")}
              />
              {errors.username && (
                <p id="username-error" role="alert" className="text-sm text-destructive">
                  {errors.username.message}
                </p>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                aria-invalid={errors.password ? true : undefined}
                aria-describedby={errors.password ? "password-error" : undefined}
                {...form.register("password")}
              />
              {errors.password && (
                <p id="password-error" role="alert" className="text-sm text-destructive">
                  {errors.password.message}
                </p>
              )}
            </div>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
