import { useEffect, useState } from "react";
import axios from "axios";
import { Button, Table, Modal, Form, Alert } from "react-bootstrap";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE;

export default function Clients() {
  const [clients, setClients] = useState([]);
  const [groups, setGroups] = useState([]);
  const [activeTab, setActiveTab] = useState("clients");
  const [loading, setLoading] = useState(false);

  const [showAdd, setShowAdd] = useState(false);
  const [broker, setBroker] = useState("dhan");

  const [form, setForm] = useState({
    name: "",
    user_id: "",
    capital: "",
    token: "",
    password: "",
  });

  // ---------------- FETCH METHODS ----------------

  const fetchClients = async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${API_BASE}/get_clients`);
      setClients(res.data || []);
    } catch (e) {
      console.error("Error loading clients:", e);
    } finally {
      setLoading(false);
    }
  };

  const fetchGroups = async () => {
    try {
      const res = await axios.get(`${API_BASE}/groups`);
      setGroups(res.data || []);
    } catch (e) {
      console.error("Error loading groups:", e);
    }
  };

  useEffect(() => {
    fetchClients();
    fetchGroups();
  }, []);

  // ---------------- ADD CLIENT ----------------

  const handleAdd = async () => {
    try {
      if (!form.user_id) return alert("Client ID required");

      const payload = {
        broker,
        client_id: form.user_id,
        display_name: form.name,
        capital: form.capital,
        creds:
          broker === "dhan"
            ? { type: "dhan", access_token: form.token }
            : {
                type: "motilal",
                client_code: form.user_id,
                password: form.password,
              },
      };

      await axios.post(`${API_BASE}/add_client`, payload);
      setShowAdd(false);
      setForm({
        name: "",
        user_id: "",
        capital: "",
        token: "",
        password: "",
      });

      fetchClients();
    } catch (e) {
      alert("Client add failed. Check console");
      console.error(e);
    }
  };

  const deleteClient = async (uid) => {
    if (!window.confirm("Delete client?")) return;
    await axios.delete(`${API_BASE}/delete_client/${uid}`);
    fetchClients();
  };

  // =========================================================

  return (
    <div style={{ padding: "20px" }}>

      {/* Toolbar */}
      <div style={{ marginBottom: 15 }}>
        <Button variant="success" onClick={() => setShowAdd(true)}>
          Add Client
        </Button>{" "}
        <Button
          variant={activeTab === "clients" ? "primary" : "outline-primary"}
          onClick={() => setActiveTab("clients")}
        >
          Clients
        </Button>{" "}
        <Button
          variant={activeTab === "groups" ? "primary" : "outline-primary"}
          onClick={() => setActiveTab("groups")}
        >
          Groups
        </Button>{" "}
        <Button variant="outline-secondary" onClick={fetchClients}>
          Refresh
        </Button>
      </div>

      {/* CLIENTS TABLE */}
      {activeTab === "clients" && (
        <Table bordered striped hover>
          <thead>
            <tr>
              <th>Client Name</th>
              <th>User ID</th>
              <th>Broker</th>
              <th>Capital</th>
              <th>Session</th>
              <th>Action</th>
            </tr>
          </thead>

          <tbody>
            {loading ? (
              <tr>
                <td colSpan="6">Loading...</td>
              </tr>
            ) : clients.length === 0 ? (
              <tr>
                <td colSpan="6">No clients yet.</td>
              </tr>
            ) : (
              clients.map((c) => (
                <tr key={c.userid}>
                  <td>{c.name}</td>
                  <td>{c.userid}</td>
                  <td>{c.broker}</td>
                  <td>{c.capital}</td>
                  <td>{c.session_active ? "✅ Active" : "❌ Offline"}</td>
                  <td>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => deleteClient(c.userid)}
                    >
                      Delete
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </Table>
      )}

      {/* GROUPS TABLE */}
      {activeTab === "groups" && (
        <Table bordered striped hover>
          <thead>
            <tr>
              <th>Group Name</th>
              <th>Clients</th>
            </tr>
          </thead>
          <tbody>
            {groups.length === 0 ? (
              <tr>
                <td colSpan="2">No groups found.</td>
              </tr>
            ) : (
              groups.map((g, i) => (
                <tr key={i}>
                  <td>{g.group_name}</td>
                  <td>
                    {(g.members || []).join(", ")}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </Table>
      )}

      {/* ADD CLIENT MODAL */}
      <Modal show={showAdd} onHide={() => setShowAdd(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Add Client</Modal.Title>
        </Modal.Header>

        <Modal.Body>
          <Form.Group className="mb-2">
            <Form.Label>Broker</Form.Label>
            <Form.Control
              as="select"
              value={broker}
              onChange={(e) => setBroker(e.target.value)}
            >
              <option value="dhan">Dhan</option>
              <option value="motilal">Motilal</option>
            </Form.Control>
          </Form.Group>

          <Form.Group className="mb-2">
            <Form.Label>Client ID</Form.Label>
            <Form.Control
              value={form.user_id}
              onChange={(e) =>
                setForm({ ...form, user_id: e.target.value })
              }
            />
          </Form.Group>

          <Form.Group className="mb-2">
            <Form.Label>Name</Form.Label>
            <Form.Control
              value={form.name}
              onChange={(e) =>
                setForm({ ...form, name: e.target.value })
              }
            />
          </Form.Group>

          <Form.Group className="mb-2">
            <Form.Label>Capital</Form.Label>
            <Form.Control
              type="number"
              value={form.capital}
              onChange={(e) =>
                setForm({ ...form, capital: e.target.value })
              }
            />
          </Form.Group>

          {broker === "dhan" ? (
            <Form.Group className="mb-2">
              <Form.Label>Access Token</Form.Label>
              <Form.Control
                value={form.token}
                onChange={(e) =>
                  setForm({ ...form, token: e.target.value })
                }
              />
            </Form.Group>
          ) : (
            <Form.Group className="mb-2">
              <Form.Label>Password</Form.Label>
              <Form.Control
                type="password"
                value={form.password}
                onChange={(e) =>
                  setForm({ ...form, password: e.target.value })
                }
              />
            </Form.Group>
          )}
        </Modal.Body>

        <Modal.Footer>
          <Button onClick={handleAdd}>Save</Button>
          <Button variant="secondary" onClick={() => setShowAdd(false)}>
            Cancel
          </Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
}
