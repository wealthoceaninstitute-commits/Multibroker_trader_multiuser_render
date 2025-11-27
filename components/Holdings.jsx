'use client';

import { useEffect, useState } from 'react';
import { Button, Card, Table } from 'react-bootstrap';
import api from './api';
import { useRouter } from 'next/navigation';

export default function Holdings() {
  const [rows, setRows] = useState([]);
  const router = useRouter();

  const fetchHoldings = async () => {
    try {
      const token = localStorage.getItem("woi_token");
      if (!token) {
        router.push("/login");
        return;
      }

      const res = await api.get('/users/get_holdings', {
        headers: {
          "x-auth-token": token,
        }
      });

      setRows(res.data?.holdings || []);
    } catch (err) {
      console.log("Error fetching holdings:", err);

      // Token expired → redirect to login
      if (err?.response?.status === 401) {
        localStorage.removeItem("woi_token");
        router.push("/login");
      }
    }
  };

  useEffect(() => { fetchHoldings(); }, []);

  return (
    <Card className="p-3">
      <div className="mb-3">
        <Button onClick={fetchHoldings}>Refresh Holdings</Button>
      </div>

      <Table bordered hover size="sm">
        <thead>
          <tr>
            <th>Select</th>
            <th>Name</th>
            <th>Symbol</th>
            <th>Quantity</th>
            <th>Buy Avg</th>
            <th>LTP</th>
            <th>PnL</th>
          </tr>
        </thead>

        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={7} className="text-center">No holdings available</td>
            </tr>
          ) : (
            rows.map((r, idx) => (
              <tr key={idx}>
                <td><input type="checkbox" /></td>
                <td>{r.name}</td>
                <td>{r.symbol}</td>
                <td>{r.quantity}</td>
                <td>{r.buy_avg}</td>
                <td>{r.ltp}</td>
                <td
                  style={{
                    color: (parseFloat(r.pnl) || 0) < 0 ? 'red' : 'green',
                    fontWeight: 'bold'
                  }}
                >
                  {(parseFloat(r.pnl) || 0).toFixed(2)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </Table>
    </Card>
  );
}
