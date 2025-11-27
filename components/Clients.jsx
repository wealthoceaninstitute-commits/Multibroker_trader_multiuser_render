"use client";

import React, { useEffect, useState } from "react";
import {
  Modal,
  Button,
  Table,
  Form,
  Row,
  Col,
  Badge,
  InputGroup,
} from "react-bootstrap";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

// ----------------------------------------------------------------------
// Helper: Auth headers
// ----------------------------------------------------------------------
function authHeaders() {
  return {
    "Content-Type": "application/json",
    "x-auth-token": localStorage.getItem("woi_token") || "",
  };
}

// ----------------------------------------------------------------------
// Main Component
// ----------------------------------------------------------------------
export default function Clients() {
  const [loading, setLoading] = useState(false);
  const [clients, setClients] = useState([]);
  const [groups, setGroups] = useState([]);

  const [showAdd, setShowAdd] = useState(false);
  const [showEdit, setShowEdit] = useState(false);

  const [editClient, setEditClient] = useState(null);

  // Add Client form
  const [form, setForm] = useState({
    broker: "",
    client_id: "",
    display_name: "",
    capital: "",
    creds: {},
  });

  // ----------------------------------------------------------------------
  // Redirect to login if not authenticated
  // ----------------------------------------------------------------------
  useEffect(() => {
    const token = localStorage.getItem("woi_token");
    if (!token) {
      window.location.href = "/login";
    } else {
      loadClients();
      loadGroups();
    }
  }, []);

  // ----------------------------------------------------------------------
  // Load Clients
  // ----------------------------------------------------------------------
  async function loadClients() {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/users/clients`, {
        method: "GET",
        headers: authHeaders(),
      });

      if (!res.ok) throw new Error(await res.text());

      const data = await res.json();
      setClients(data.clients || []);
    } catch (err) {
      console.error("Load clients error:", err);
    } finally {
      setLoading(false);
    }
  }

  // ----------------------------------------------------------------------
  // Load Groups
  // ----------------------------------------------------------------------
  async function loadGroups() {
    try {
      const res = await fetch(`${API_BASE}/users/groups`, {
        method: "GET",
        headers: authHeaders(),
      });

      if (!res.ok) return;

      const data = await res.json();
      setGroups(data.groups || []);
    } catch (err) {
      console.error("Load groups error:", err);
    }
  }

  // ----------------------------------------------------------------------
  // Add New Client
  // ----------------------------------------------------------------------
  async function addClient() {
    try {
      setLoading(true);

      const res = await fetch(`${API_BASE}/users/add_client`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(form),
      });

      if (!res.ok) throw new Error(await res.text());

      setShowAdd(false);
      setForm({
        broker: "",
        client_id: "",
        display_name: "",
        capital: "",
        creds: {},
      });

      loadClients();
    } catch (err) {
      alert("Failed to add client: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  // ----------------------------------------------------------------------
  // Edit Client
  // ----------------------------------------------------------------------
  async function saveEditClient() {
    try {
      setLoading(true);

      const res = await fetch(`${API_BASE}/users/edit_client`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(editClient),
      });

      if (!res.ok) throw new Error(await res.text());

      setShowEdit(false);
      setEditClient(null);

      loadClients();
    } catch (err) {
      alert("Failed to update client: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  // ----------------------------------------------------------------------
  // Delete Client
  // ----------------------------------------------------------------------
  async function deleteClient(broker, client_id) {
    if (!confirm("Delete this client?")) return;

    try {
      setLoading(true);

      const res = await fetch(`${API_BASE}/users/delete_client`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ broker, client_id }),
      });

      if (!res.ok) throw new Error(await res.text());

      loadClients();
    } catch (err) {
      alert("Failed to delete: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  // ----------------------------------------------------------------------
  // UI Section
  // ----------------------------------------------------------------------

  return (
    <div className="container mt-4">
      <h2 className="mb-3">Clients</h2>

      <Button className="mb-3" onClick={() => setShowAdd(true)}>
        ➕ Add Client
      </Button>

      <Table striped bordered hover>
        <thead>
          <tr>
            <th>Broker</th>
            <th>Client ID</th>
            <th>Name</th>
            <th>Capital</th>
            <th>Groups</th>
            <th style={{ width: "180px" }}>Actions</th>
          </tr>
        </thead>

        <tbody>
          {clients.map((c, idx) => (
            <tr key={idx}>
              <td>{c.broker}</td>
              <td>{c.client_id}</td>
              <td>{c.display_name}</td>
              <td>{c.capital}</td>
              <td>
                {(c.groups || []).map((g, i) => (
                  <Badge key={i} className="me-1 bg-primary">
                    {g}
                  </Badge>
                ))}
              </td>
              <td>
                <Button
                  size="sm"
                  variant="warning"
                  className="me-2"
                  onClick={() => {
                    setEditClient(c);
                    setShowEdit(true);
                  }}
                >
                  Edit
                </Button>

                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => deleteClient(c.broker, c.client_id)}
                >
                  Delete
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>

      {/* --------------------------------------------------------------
          Add Client Modal
      ---------------------------------------------------------------- */}
      <Modal show={showAdd} onHide={() => setShowAdd(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Add New Client</Modal.Title>
        </Modal.Header>

        <Modal.Body>
          <Form>
            <Form.Group className="mb-2">
              <Form.Label>Broker</Form.Label>
              <Form.Select
                value={form.broker}
                onChange={(e) =>
                  setForm({ ...form, broker: e.target.value })
                }
              >
                <option value="">Select Broker</option>
                <option value="dhan">Dhan</option>
                <option value="motilal">Motilal Oswal</option>
              </Form.Select>
            </Form.Group>

            <Form.Group className="mb-2">
              <Form.Label>Client ID</Form.Label>
              <Form.Control
                value={form.client_id}
                onChange={(e) =>
                  setForm({ ...form, client_id: e.target.value })
                }
              />
            </Form.Group>

            <Form.Group className="mb-2">
              <Form.Label>Name</Form.Label>
              <Form.Control
                value={form.display_name}
                onChange={(e) =>
                  setForm({ ...form, display_name: e.target.value })
                }
              />
            </Form.Group>

            <Form.Group className="mb-2">
              <Form.Label>Capital</Form.Label>
              <Form.Control
                value={form.capital}
                onChange={(e) =>
                  setForm({ ...form, capital: e.target.value })
                }
              />
            </Form.Group>

            {/* Broker Credentials */}
            {form.broker === "dhan" && (
              <Form.Group className="mb-2">
                <Form.Label>Dhan Access Token</Form.Label>
                <Form.Control
                  onChange={(e) =>
                    setForm({
                      ...form,
                      creds: { type: "dhan", access_token: e.target.value },
                    })
                  }
                />
              </Form.Group>
            )}

            {form.broker === "motilal" && (
              <>
                <Form.Group className="mb-2">
                  <Form.Label>Password</Form.Label>
                  <Form.Control
                    onChange={(e) =>
                      setForm({
                        ...form,
                        creds: { ...form.creds, password: e.target.value },
                      })
                    }
                  />
                </Form.Group>

                <Form.Group className="mb-2">
                  <Form.Label>MPIN</Form.Label>
                  <Form.Control
                    onChange={(e) =>
                      setForm({
                        ...form,
                        creds: { ...form.creds, mpin: e.target.value },
                      })
                    }
                  />
                </Form.Group>
              </>
            )}
          </Form>
        </Modal.Body>

        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowAdd(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={addClient}>
            Save Client
          </Button>
        </Modal.Footer>
      </Modal>

      {/* --------------------------------------------------------------
          Edit Client Modal
      ---------------------------------------------------------------- */}
      <Modal show={showEdit} onHide={() => setShowEdit(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Edit Client</Modal.Title>
        </Modal.Header>

        <Modal.Body>
          {editClient && (
            <Form>
              <Form.Group className="mb-2">
                <Form.Label>Display Name</Form.Label>
                <Form.Control
                  value={editClient.display_name}
                  onChange={(e) =>
                    setEditClient({
                      ...editClient,
                      display_name: e.target.value,
                    })
                  }
                />
              </Form.Group>

              <Form.Group className="mb-2">
                <Form.Label>Capital</Form.Label>
                <Form.Control
                  value={editClient.capital}
                  onChange={(e) =>
                    setEditClient({
                      ...editClient,
                      capital: e.target.value,
                    })
                  }
                />
              </Form.Group>
            </Form>
          )}
        </Modal.Body>

        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowEdit(false)}>
            Cancel
          </Button>

          <Button variant="primary" onClick={saveEditClient}>
            Save Changes
          </Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
}
