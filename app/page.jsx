'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Container, Row, Col, Card, Tabs, Tab, Form, Button } from 'react-bootstrap';
import { setCurrentUser } from '../src/lib/userSession';

export default function HomePage() {
  const router = useRouter();
  const [tab, setTab] = useState('login');

  // Simple local state – later we will connect to backend
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [signupForm, setSignupForm] = useState({ username: '', email: '', password: '' });

  const handleLoginChange = (e) => {
    const { name, value } = e.target;
    setLoginForm((prev) => ({ ...prev, [name]: value }));
  };

  const handleSignupChange = (e) => {
    const { name, value } = e.target;
    setSignupForm((prev) => ({ ...prev, [name]: value }));
  };

  const handleLoginSubmit = (e) => {
    e.preventDefault();
    // TODO: call backend /login with loginForm
    // Frontend-only for now: remember user & go to trader
    setCurrentUser(loginForm.username);
    router.push('/trader');
  };

  const handleSignupSubmit = (e) => {
    e.preventDefault();
    // TODO: call backend /users/create with signupForm
    // Frontend-only for now: remember user & go to trader
    setCurrentUser(signupForm.username);
    router.push('/trader');
  };

  return (
    <Container className="d-flex align-items-center justify-content-center" style={{ minHeight: '100vh' }}>
      <Row className="w-100 justify-content-center">
        <Col xs={12} md={8} lg={6}>
          <Card>
            <Card.Body>
              <h3 className="text-center mb-3">Wealth Ocean – Login</h3>
              <p className="text-muted text-center mb-4">
                Multi-broker, multi-user trading panel
              </p>

              <Tabs
                id="auth-tabs"
                activeKey={tab}
                onSelect={(k) => setTab(k || 'login')}
                className="mb-3"
                justify
              >
                <Tab eventKey="login" title="Login">
                  <Form onSubmit={handleLoginSubmit}>
                    <Form.Group className="mb-3" controlId="loginUsername">
                      <Form.Label>User ID / Username</Form.Label>
                      <Form.Control
                        type="text"
                        name="username"
                        value={loginForm.username}
                        onChange={handleLoginChange}
                        placeholder="Enter your user id"
                        required
                      />
                    </Form.Group>

                    <Form.Group className="mb-3" controlId="loginPassword">
                      <Form.Label>Password</Form.Label>
                      <Form.Control
                        type="password"
                        name="password"
                        value={loginForm.password}
                        onChange={handleLoginChange}
                        placeholder="Enter your password"
                        required
                      />
                    </Form.Group>

                    <div className="d-grid">
                      <Button type="submit">Login</Button>
                    </div>
                  </Form>
                </Tab>

                <Tab eventKey="signup" title="Create New User">
                  <Form onSubmit={handleSignupSubmit}>
                    <Form.Group className="mb-3" controlId="signupUsername">
                      <Form.Label>User ID / Username</Form.Label>
                      <Form.Control
                        type="text"
                        name="username"
                        value={signupForm.username}
                        onChange={handleSignupChange}
                        placeholder="Choose a user id"
                        required
                      />
                    </Form.Group>

                    <Form.Group className="mb-3" controlId="signupEmail">
                      <Form.Label>Email (optional)</Form.Label>
                      <Form.Control
                        type="email"
                        name="email"
                        value={signupForm.email}
                        onChange={handleSignupChange}
                        placeholder="you@example.com"
                      />
                    </Form.Group>

                    <Form.Group className="mb-3" controlId="signupPassword">
                      <Form.Label>Password</Form.Label>
                      <Form.Control
                        type="password"
                        name="password"
                        value={signupForm.password}
                        onChange={handleSignupChange}
                        placeholder="Create a password"
                        required
                      />
                    </Form.Group>

                    <div className="d-grid">
                      <Button type="submit" variant="success">
                        Create User
                      </Button>
                    </div>
                  </Form>
                </Tab>
              </Tabs>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </Container>
  );
}
