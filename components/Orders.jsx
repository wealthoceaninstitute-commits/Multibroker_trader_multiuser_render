'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Card, Table, Tabs, Tab, Badge, Modal, Form, Spinner, InputGroup } from 'react-bootstrap';
import api from './api';
import { useRouter } from 'next/navigation';

/* == tiny inline icons (no extra deps) == */
const SearchIcon = (props) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);
const XCircle = (props) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
    <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
  </svg>
);

const AUTO_REFRESH_MS = 3000;

/* display -> canonical order type */
const DISPLAY_TO_CANON = {
  NO_CHANGE: 'NO_CHANGE',
  LIMIT: 'LIMIT',
  MARKET: 'MARKET',
  STOPLOSS: 'STOPLOSS',
  'SL MARKET': 'STOPLOSS_MARKET',
};

/* ---------- Broker-agnostic symbol parsing ---------- */
const MONTH_MAP = {
  JAN:'JAN', FEB:'FEB', MAR:'MAR', APR:'APR', MAY:'MAY', JUN:'JUN',
  JUL:'JUL', AUG:'AUG', SEP:'SEP', SEPT:'SEP', OCT:'OCT', NOV:'NOV', DEC:'DEC'
};
const sanitize = (s) => String(s || '')
  .toUpperCase()
  .replace(/[\u00A0\u1680\u2000-\u200B\u202F\u205F\u3000]/g, ' ')
  .replace(/[–—−]/g, '-')
  .replace(/\s+/g, ' ')
  .trim();
const isMonthHead = (t) => /^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)/.test(t);
const isYear = (t) => /^\d{4}$/.test(t);
const isDay = (t) => /^\d{1,2}$/.test(t);
const isTailFlag = (t) => /^(FUT|OPT|CE|PE)$/.test(t);

function parseSymbol(raw) {
  const u = sanitize(raw);
  const tokens = u.split(/[\s\-_/]+/).filter(Boolean);

  const undParts = [];
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (isTailFlag(t) || isYear(t) || isMonthHead(t)) {
      if (undParts.length && isDay(undParts.length - 1)) undParts.pop();
      break;
    }
    undParts.push(t);
  }
  const und = undParts.join('').replace(/[^A-Z0-9]/g, '');

  let mon=null, year=null, m;
  m = u.match(/\b(\d{1,2})[-\s]*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*[-\s]*((?:19|20)\d{2})\b/);
  if (m) { mon = MONTH_MAP[m[2]]; year = m[3]; }
  if (!mon) {
    m = u.match(/\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*[-\s]*((?:19|20)\d{2})\b/);
    if (m) { mon = MONTH_MAP[m[1]]; year = m[2]; }
  }

  const kind = /\b(CE|PE)\b/.test(u) ? 'OPT' : 'FUT';
  return { und, mon, year, kind };
}
function canonicalKey(raw, { includeKind = false } = {}) {
  const { und, mon, year, kind } = parseSymbol(raw);
  const base = (und && mon && year) ? `${und}-${mon}${year}` : sanitize(raw).replace(/[^A-Z0-9]/g, '');
  return includeKind ? `${base}-${kind}` : base;
}

/* ---------------------------------------------------- */

export default function Orders() {

  const router = useRouter();

  const [orders, setOrders] = useState({ pending: [], traded: [], rejected: [], cancelled: [], others: [] });
  const [selectedIds, setSelectedIds] = useState({});
  const [lastUpdated, setLastUpdated] = useState(null);

  // search state
  const [query, setQuery] = useState('');
  const qTokens = useMemo(() => query.trim().split(/\s+/).filter(Boolean), [query]);

  // modify modal
  const [showModify, setShowModify] = useState(false);
  const [modifyTarget, setModifyTarget] = useState(null);
  const [modQty, setModQty] = useState('');
  const [modPrice, setModPrice] = useState('');
  const [modTrig, setModTrig] = useState('');
  const [modType, setModType] = useState('NO_CHANGE');
  const [modLTP, setModLTP] = useState('—');
  const [modSaving, setModSaving] = useState(false);

  const busyRef = useRef(false);
  const snapRef = useRef('');
  const timerRef = useRef(null);
  const abortRef = useRef(null);
  const modalContainerRef = useRef(null);

  /** Login redirect **/
  useEffect(() => {
    const token = localStorage.getItem("woi_token");
    if (!token) router.push("/login");
  }, []);

  useEffect(() => {
    if (typeof document !== 'undefined') {
      const el = document.createElement('div');
      el.id = 'orders-modal-root';
      document.body.appendChild(el);
      modalContainerRef.current = el;
      return () => {
        try { document.body.removeChild(el); } catch {}
      };
    }
  }, []);

  /* ===== fetch with token ===== */
  const fetchAll = async () => {
    if (busyRef.current) return;
    if (typeof document !== 'undefined' && document.hidden) return;

    const token = localStorage.getItem("woi_token");
    if (!token) {
      router.push("/login");
      return;
    }

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await api.get('/users/get_orders', {
        signal: controller.signal,
        headers: {
          "x-auth-token": token
        }
      });

      const next = {
        pending: res.data?.pending || [],
        traded: res.data?.traded || [],
        rejected: res.data?.rejected || [],
        cancelled: res.data?.cancelled || [],
        others: res.data?.others || [],
      };
      const snap = JSON.stringify(next);
      if (snap !== snapRef.current) {
        snapRef.current = snap;
        setOrders(next);
        setLastUpdated(new Date());
      }
    } catch (e) {
      if (e?.response?.status === 401) {
        localStorage.removeItem("woi_token");
        router.push("/login");
      }
      if (e.name !== 'CanceledError') console.warn("Orders refresh failed:", e.message);
    } finally {
      abortRef.current = null;
    }
  };

  useEffect(() => {
    fetchAll();
    timerRef.current = setInterval(fetchAll, AUTO_REFRESH_MS);
    return () => {
      clearInterval(timerRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  /* ===== Helpers ===== */
  const rowKey = (row) =>
    String(row.order_id ?? `${row.name ?? ''}|${row.symbol ?? ''}|${row.status ?? ''}`);

  const toggle = (rowId) =>
    setSelectedIds((prev) => ({ ...prev, [rowId]: !prev[rowId] }));

  const getSelectedPending = () => {
    const picked = [];
    orders.pending.forEach((row) => {
      const id = rowKey(row);
      if (selectedIds[id]) {
        picked.push({
          name: row.name,
          symbol: row.symbol,
          price: row.price,
          order_id: row.order_id,
          status: row.status,
          broker: row.broker ?? null,
          client_id: row.client_id ?? null,
        });
      }
    });
    return picked;
  };

  /* ===== Cancel ===== */
  const cancelSelected = async () => {
    const selected = getSelectedPending();
    if (selected.length === 0) return alert("No orders selected.");

    const token = localStorage.getItem("woi_token");
    if (!token) return router.push("/login");

    try {
      busyRef.current = true;
      const res = await api.post('/users/cancel_order',
        { orders: selected },
        { headers: { "x-auth-token": token } }
      );
      alert("Cancel request sent.");
      setSelectedIds({});
      fetchAll();
    } catch (err) {
      alert("Cancel failed: " + (err.response?.data || err.message));
    } finally {
      busyRef.current = false;
    }
  };

  /* ===== Modify ===== */
  const requires = (displayType) => {
    const canon = DISPLAY_TO_CANON[displayType] || displayType;
    return { price: ['LIMIT','STOPLOSS'].includes(canon), trig: ['STOPLOSS','STOPLOSS_MARKET'].includes(canon), canon };
  };

  const tryFetchLTP = async (symbol) => {
    const token = localStorage.getItem("woi_token");
    if (!token) return;

    try {
      const r = await api.get('/users/ltp', {
        params: { symbol },
        headers: { "x-auth-token": token }
      });
      const v = Number(r?.data?.ltp);
      if (!isNaN(v)) setModLTP(v.toFixed(2));
    } catch {}
  };

  const openModify = () => {
    const chosen = getSelectedPending();
    if (chosen.length === 0) return alert("Select pending order(s) to modify.");

    const key0 = canonicalKey(chosen[0].symbol);
    const allSame = chosen.every((c) => canonicalKey(c.symbol) === key0);
    if (!allSame) {
      alert("All selected orders must have the same base symbol.");
      return;
    }

    setModifyTarget({ symbol: chosen[0].symbol, orders: chosen });
    setModQty('');
    setModPrice('');
    setModTrig('');
    setModType('NO_CHANGE');
    setModLTP('—');
    setShowModify(true);
    tryFetchLTP(chosen[0].symbol);
  };

  const submitModify = async () => {
    if (!modifyTarget) return;

    const need = requires(modType);
    const token = localStorage.getItem("woi_token");
    if (!token) return router.push("/login");

    const mods = modifyTarget.orders.map((o) => {
      const payload = {
        name: o.name,
        symbol: o.symbol,
        order_id: o.order_id,
        broker: o.broker,
        client_id: o.client_id,
      };

      if (modType !== 'NO_CHANGE') payload.ordertype = need.canon;
      if (modQty !== '') payload.quantity = parseInt(modQty);
      if (modPrice !== '') payload.price = parseFloat(modPrice);
      if (modTrig !== '') payload.triggerprice = parseFloat(modTrig);

      return api.post('/users/modify_order',
        { order: payload },
        { headers: { "x-auth-token": token } }
      );
    });

    try {
      setModSaving(true);
      await Promise.allSettled(mods);
      alert("Order(s) modified.");
      setShowModify(false);
      setSelectedIds({});
      fetchAll();
    } catch (err) {
      alert("Modify failed: " + err.message);
    } finally {
      setModSaving(false);
    }
  };

  /* ===== Search + Filter ===== */
  const escapeReg = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const highlightSymbol = (sym) => {
    const text = sym ?? 'N/A';
    if (!text || qTokens.length === 0) return text;
    try {
      const re = new RegExp(`(${qTokens.map(escapeReg).join('|')})`, 'gi');
      return text.split(re).map((p, i) => re.test(p)
        ? <mark key={i} className="hl">{p}</mark>
        : <span key={i}>{p}</span>);
    } catch {
      return text;
    }
  };

  const filterBySymbol = (rows) => {
    if (qTokens.length === 0) return rows;
    return rows.filter((r) =>
      qTokens.every((t) =>
        (r.symbol ?? '').toUpperCase().includes(t.toUpperCase())
      )
    );
  };

  const filtered = useMemo(() => ({
    pending: filterBySymbol(orders.pending),
    traded: filterBySymbol(orders.traded),
    rejected: filterBySymbol(orders.rejected),
    cancelled: filterBySymbol(orders.cancelled),
    others: filterBySymbol(orders.others),
  }), [orders, qTokens]);

  /* ===== Modal Renderer ===== */
  const renderModifyModal = () => {
    if (!modifyTarget) return null;

    const need = requires(modType);
    const multi = modifyTarget.orders.length > 1;

    return (
      <Modal
        container={modalContainerRef.current}
        show={showModify}
        onHide={() => setShowModify(false)}
        backdrop="static"
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title>{multi ? "Modify Orders" : "Modify Order"}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <div className="mb-2">
            <strong>Symbol:</strong> {modifyTarget.symbol}
          </div>

          <div className="mb-2">
            <div className="text-muted small">LTP</div>
            <div style={{ fontWeight: 700 }}>{modLTP}</div>
          </div>

          <Form>
            <Form.Group className="mb-2">
              <Form.Label>Quantity</Form.Label>
              <Form.Control
                type="number"
                value={modQty}
                onChange={(e) => setModQty(e.target.value)}
              />
            </Form.Group>

            <Form.Group className="mb-2">
              <Form.Label>
                Price {need.price ? <span className="text-danger">*</span> : ""}
              </Form.Label>
              <Form.Control
                type="number"
                value={modPrice}
                onChange={(e) => setModPrice(e.target.value)}
              />
            </Form.Group>

            <Form.Group className="mb-3">
              <Form.Label>
                Trigger {need.trig ? <span className="text-danger">*</span> : ""}
              </Form.Label>
              <Form.Control
                type="number"
                value={modTrig}
                onChange={(e) => setModTrig(e.target.value)}
              />
            </Form.Group>

            <Form.Group>
              <Form.Label>Order Type</Form.Label>
              {['NO_CHANGE', 'LIMIT', 'MARKET', 'STOPLOSS', 'SL MARKET'].map((t) => (
                <Form.Check
                  key={t}
                  inline
                  type="radio"
                  name="modType"
                  label={t}
                  checked={modType === t}
                  onChange={() => setModType(t)}
                />
              ))}
            </Form.Group>
          </Form>
        </Modal.Body>

        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowModify(false)}>
            Close
          </Button>
          <Button variant="warning" onClick={submitModify} disabled={modSaving}>
            {modSaving && <Spinner size="sm" className="me-2" />}
            Modify
          </Button>
        </Modal.Footer>
      </Modal>
    );
  };

  /* ===== Table renderer ===== */
  const renderTable = (rows) => (
    <Table bordered hover size="sm">
      <thead>
        <tr>
          <th>Select</th>
          <th>Name</th>
          <th>Symbol</th>
          <th>Type</th>
          <th>Qty</th>
          <th>Price</th>
          <th>Status</th>
          <th>Order ID</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr><td colSpan={8} className="text-center">No data</td></tr>
        ) : (
          rows.map((row) => {
            const idKey = rowKey(row);
            return (
              <tr key={idKey}>
                <td>
                  <input
                    type="checkbox"
                    checked={!!selectedIds[idKey]}
                    onChange={() => toggle(idKey)}
                  />
                </td>
                <td>{row.name ?? 'N/A'}</td>
                <td>{highlightSymbol(row.symbol)}</td>
                <td>{row.transaction_type ?? 'N/A'}</td>
                <td>{row.quantity ?? 'N/A'}</td>
                <td>{row.price ?? 'N/A'}</td>
                <td>{row.status ?? 'N/A'}</td>
                <td>{row.order_id ?? 'N/A'}</td>
              </tr>
            );
          })
        )}
      </tbody>
    </Table>
  );

  return (
    <Card className="p-3">
      {/* Toolbar */}
      <div className="mb-3 d-flex gap-2 align-items-center flex-wrap">
        <Button onClick={fetchAll}>Refresh Orders</Button>
        <Button variant="warning" onClick={openModify}>Modify Order</Button>
        <Button variant="danger" onClick={cancelSelected}>Cancel Order</Button>

        <Badge bg="info" className="ms-1">
          {Object.values(selectedIds).filter(Boolean).length} selected
        </Badge>

        <div className="ms-auto">
          <InputGroup>
            <InputGroup.Text><SearchIcon /></InputGroup.Text>
            <Form.Control
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search symbol…"
            />
            {query && (
              <Button variant="outline-secondary" onClick={() => setQuery('')}>
                <XCircle />
              </Button>
            )}
          </InputGroup>
        </div>

        <Badge bg="secondary" className="ms-2">
          Refresh {AUTO_REFRESH_MS / 1000}s
          {lastUpdated && ` · ${lastUpdated.toLocaleTimeString()}`}
        </Badge>
      </div>

      <Tabs defaultActiveKey="pending" className="mb-3">
        <Tab eventKey="pending" title="Pending">{renderTable(filtered.pending)}</Tab>
        <Tab eventKey="traded" title="Traded">{renderTable(filtered.traded)}</Tab>
        {renderTable(filtered.rejected)}
        <Tab eventKey="rejected" title="Rejected" />
        <Tab eventKey="cancelled" title="Cancelled">{renderTable(filtered.cancelled)}</Tab>
        <Tab eventKey="others" title="Others">{renderTable(filtered.others)}</Tab>
      </Tabs>

      {renderModifyModal()}
    </Card>
  );
}
