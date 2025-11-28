"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Container,
  Tabs,
  Tab,
  Form,
  Button,
  Alert,
  Spinner,
} from "react-bootstrap";
import {
  getCurrentUser,
  setCurrentUser,
} from "../../src/lib/userSession";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

export default function LoginPage() {
  const router = useRouter();

  const [activeTab, setActiveTab] = useState("login");
  const [loginForm, setLoginForm] = useState({
    username: "",
    password: "",
  });
  const [signupForm, setSignupForm] = useState({
    username: "",
    password: "",
    confirmPassword: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  // If already logged in, go directly to trader
  useEffect(() => {
    const existing = getCurrentUser();
    if (existing && existing.username) {
      router.replace("/trader");
    }
  }, [router]);

  // ---------- handlers ----------

  const handleLoginChange = (e) => {
    const { name, value } = e.target;
    setLoginForm((prev) => ({ ...prev, [name]: value }));
  };

  const handleSignupChange = (e) => {
    const { name, value } = e.target;
    setSignupForm((prev) => ({ ...prev, [name]: value }));
  };

  async function handleLoginSubmit(e) {
    e.preventDefault();
    setError("");
    setMessage("");

    if (!loginForm.username || !loginForm.password) {
      setError("Please enter both User ID and Password.");
      return;
    }

    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: loginForm.username,
          password: loginForm.password,
        }),
      });

      if (!resp.ok) {
        let detail = "Login failed";
        try {
          const data = await resp.json();
          if (data?.detail) detail = data.detail;
        } catch {
          // ignore JSON error
        }
        throw new Error(detail);
      }

      const data = await resp.json().catch(() => ({}));

      // Save to one consistent place
      setCurrentUser({
        username: data.username || loginForm.username,
        token: data.token || "",
      });

      // Go to trader page and STAY there
      router.push("/trader");
    } catch (err) {
      console.error("Login error:", err);
      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleSignupSubmit(e) {
    e.preventDefault();
    setError("");
    setMessage("");

    if (
      !signupForm.username ||
      !signupForm.password ||
      !signupForm.confirmPassword
    ) {
      setError("Please fill all fields.");
      return;
    }

    if (signupForm.password !== signupForm.confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/create_user`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: signupForm.username,
          password: signupForm.password,
        }),
      });

      if (!resp.ok) {
        let detail = "Failed to create user";
        try {
          const data = await resp.json();
          if (data?.detail) detail = data.detail;
        } catch {
          // ignore
        }
        throw new Error(detail);
      }

      setMessage("User created successfully. You can now login.");
      setActiveTab("login");
      setSignupForm({ username: "", password: "", confirmPassword: "" });
    } catch (err) {
      console.error("Signup error:", err);
      setError(err.message || "Failed to create user");
    } finally {
      setLoading(false);
    }
  }

  // ---------- JSX ----------

  return (
    <Container className="mt-5" style={{ maxWidth: "600px" }}>
      <h1 className="text-center mb-2">Wealth Ocean – Login</h1>
      <p className="text-center text-muted">
        Multi-broker, multi-user trading panel
      </p>

      {error && <Alert variant="danger">{error}</Alert>}
      {message && <Alert variant="success">{message}</Alert>}

      <Tabs
        id="login-tabs"
        activeKey={activeTab}
        onSelect={(k) => k && setActiveTab(k)}
        className="mb-3"
      >
        <Tab eventKey="login" title="Login">
          <Form onSubmit={handleLoginSubmit} className="mt-3">
            <Form.Group className="mb-3" controlId="login-username">
              <Form.Label>User ID / Username</Form.Label>
              <Form.Control
                type="text"
                name="username"
                placeholder="Enter your user id"
                value={loginForm.username}
                onChange={handleLoginChange}
              />
            </Form.Group>
            <Form.Group className="mb-3" controlId="login-password">
              <Form.Label>Password</Form.Label>
              <Form.Control
                type="password"
                name="password"
                placeholder="Enter your password"
                value={loginForm.password}
                onChange={handleLoginChange}
              />
            </Form.Group>
            <Button type="submit" disabled={loading}>
              {loading ? (
                <>
                  <Spinner
                    as="span"
                    animation="border"
                    size="sm"
                    className="me-2"
                  />
                  Logging in...
                </>
              ) : (
                "Login"
              )}
            </Button>
          </Form>
        </Tab>

        <Tab eventKey="signup" title="Create New User">
          <Form onSubmit={handleSignupSubmit} className="mt-3">
            <Form.Group className="mb-3" controlId="signup-username">
              <Form.Label>User ID / Username</Form.Label>
              <Form.Control
                type="text"
                name="username"
                placeholder="Choose a username"
                value={signupForm.username}
                onChange={handleSignupChange}
              />
            </Form.Group>
            <Form.Group className="mb-3" controlId="signup-password">
              <Form.Label>Password</Form.Label>
              <Form.Control
                type="password"
                name="password"
                placeholder="Create a password"
                value={signupForm.password}
                onChange={handleSignupChange}
              />
            </Form.Group>
            <Form.Group className="mb-3" controlId="signup-confirm">
              <Form.Label>Confirm Password</Form.Label>
              <Form.Control
                type="password"
                name="confirmPassword"
                placeholder="Re-enter password"
                value={signupForm.confirmPassword}
                onChange={handleSignupChange}
              />
            </Form.Group>
            <Button type="submit" disabled={loading}>
              {loading ? "Creating..." : "Create User"}
            </Button>
          </Form>
        </Tab>
      </Tabs>
    </Container>
  );
}
