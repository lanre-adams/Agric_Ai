"use client";

import { useEffect, useState } from "react";
import { signInWithEmailAndPassword } from "firebase/auth";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "../../lib/firebase";

export default function LoginPage() {
  const router = useRouter();

  const [continueSave, setContinueSave] = useState(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setContinueSave(params.get("continueSave") === "1");
  }, []);

  const signupLink = continueSave ? "/signup?continueSave=1" : "/signup";

  async function handleLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage("");

    if (!email.trim()) {
      setErrorMessage("Please enter your email address.");
      return;
    }

    if (!password) {
      setErrorMessage("Please enter your password.");
      return;
    }

    try {
      setIsLoading(true);

      await signInWithEmailAndPassword(auth, email.trim(), password);

      router.push(continueSave ? "/?continueSave=1" : "/");
    } catch (error: any) {
      if (
        error?.code === "auth/invalid-credential" ||
        error?.code === "auth/user-not-found" ||
        error?.code === "auth/wrong-password"
      ) {
        setErrorMessage("Email or password is incorrect.");
      } else if (error?.code === "auth/invalid-email") {
        setErrorMessage("Please enter a valid email address.");
      } else {
        setErrorMessage("Login failed. Please try again.");
      }
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main style={styles.page}>
      <section style={styles.card}>
        <div style={styles.badge}>Tagintell Farm Watch</div>

        <h1 style={styles.title}>Welcome back</h1>

        <p style={styles.subtitle}>
          {continueSave
            ? "Log in to save the farm analysis you just completed."
            : "Log in to view your saved farms and analysis history."}
        </p>

        <form onSubmit={handleLogin} style={styles.form}>
          <label style={styles.label}>
            Email address
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              style={styles.input}
              autoComplete="email"
            />
          </label>

          <label style={styles.label}>
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Your password"
              style={styles.input}
              autoComplete="current-password"
            />
          </label>

          {errorMessage && <p style={styles.error}>{errorMessage}</p>}

          <button type="submit" disabled={isLoading} style={styles.button}>
            {isLoading ? "Logging in..." : "Log in"}
          </button>
        </form>

        <p style={styles.footerText}>
          Do not have an account?{" "}
          <Link href={signupLink} style={styles.link}>
            Create one
          </Link>
        </p>
      </section>
    </main>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: "100vh",
    background:
      "radial-gradient(circle at top, rgba(16, 185, 129, 0.18), transparent 32%), #020617",
    color: "#f8fafc",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "24px",
  },
  card: {
    width: "100%",
    maxWidth: "440px",
    background: "rgba(15, 23, 42, 0.92)",
    border: "1px solid rgba(148, 163, 184, 0.25)",
    borderRadius: "20px",
    padding: "28px",
    boxShadow: "0 24px 80px rgba(0,0,0,0.35)",
  },
  badge: {
    display: "inline-flex",
    padding: "8px 12px",
    borderRadius: "999px",
    background: "rgba(16, 185, 129, 0.12)",
    color: "#34d399",
    fontWeight: 700,
    fontSize: "13px",
    marginBottom: "18px",
  },
  title: {
    fontSize: "30px",
    lineHeight: 1.1,
    margin: "0 0 10px",
  },
  subtitle: {
    color: "#94a3b8",
    lineHeight: 1.6,
    margin: "0 0 24px",
  },
  form: {
    display: "grid",
    gap: "16px",
  },
  label: {
    display: "grid",
    gap: "8px",
    color: "#cbd5e1",
    fontSize: "14px",
    fontWeight: 600,
  },
  input: {
    width: "100%",
    borderRadius: "12px",
    border: "1px solid rgba(148, 163, 184, 0.35)",
    background: "#020617",
    color: "#f8fafc",
    padding: "13px 14px",
    fontSize: "15px",
    outline: "none",
  },
  error: {
    background: "rgba(239, 68, 68, 0.12)",
    color: "#fecaca",
    border: "1px solid rgba(239, 68, 68, 0.35)",
    borderRadius: "12px",
    padding: "12px",
    margin: 0,
    fontSize: "14px",
  },
  button: {
    border: "none",
    borderRadius: "12px",
    padding: "14px 16px",
    background: "#10b981",
    color: "#022c22",
    fontWeight: 800,
    fontSize: "15px",
    cursor: "pointer",
  },
  footerText: {
    color: "#94a3b8",
    marginTop: "20px",
    textAlign: "center",
  },
  link: {
    color: "#34d399",
    fontWeight: 700,
    textDecoration: "none",
  },
};