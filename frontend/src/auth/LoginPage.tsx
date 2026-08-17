import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "@/components/ui/sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { useAuth } from "./AuthProvider";
import { Brand } from "@/components/brand";

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

export function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
  });

  async function onSubmit(values: z.infer<typeof schema>) {
    try {
      await login(values.email, values.password);
      nav("/kindling/dashboard");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-2 text-center">
          <div className="flex justify-center">
            <Brand />
          </div>
          <CardTitle>Welcome back</CardTitle>
          <CardDescription>Sign in to your Kindling account.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="email">Email</FieldLabel>
                <Input id="email" type="email" {...register("email")} />
                {errors.email && <FieldError>{errors.email.message}</FieldError>}
              </Field>
              <Field>
                <FieldLabel htmlFor="password">Password</FieldLabel>
                <Input id="password" type="password" {...register("password")} />
                {errors.password && <FieldError>{errors.password.message}</FieldError>}
              </Field>
              <Button type="submit" disabled={isSubmitting} className="w-full">
                {isSubmitting ? "Signing in…" : "Sign in"}
              </Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
