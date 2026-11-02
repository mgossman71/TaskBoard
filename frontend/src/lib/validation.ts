import { z } from "zod";

/** Mirrors the server-side password policy (backend/forgeboard/schemas/auth.py). */
export const passwordSchema = z
  .string()
  .min(10, "Use at least 10 characters")
  .max(128, "Use at most 128 characters")
  .refine(
    (v) => [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(v)).length >= 3,
    "Include at least three of: lowercase, uppercase, digits, symbols",
  );

export const emailSchema = z.string().trim().min(1, "Email is required").pipe(z.email("Enter a valid email address"));

export const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, "Password is required"),
});

export const registerSchema = z
  .object({
    display_name: z.string().trim().min(1, "Name is required").max(100, "Use at most 100 characters"),
    email: emailSchema,
    password: passwordSchema,
    confirm: z.string(),
  })
  .refine((d) => d.password === d.confirm, { path: ["confirm"], message: "Passwords do not match" });

export const resetSchema = z
  .object({ password: passwordSchema, confirm: z.string() })
  .refine((d) => d.password === d.confirm, { path: ["confirm"], message: "Passwords do not match" });

export const projectSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(120, "Use at most 120 characters"),
  key: z
    .string()
    .trim()
    .regex(/^[A-Z][A-Z0-9]{1,9}$/, "2–10 uppercase letters/digits, starting with a letter"),
  description: z.string().max(5000, "Use at most 5000 characters"),
});

export const taskTitleSchema = z.string().trim().min(1, "Title is required").max(200, "Use at most 200 characters");
