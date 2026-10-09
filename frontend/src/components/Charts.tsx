import React from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface StatusChartProps {
  data: Record<string, number>;
}

export const StatusChart: React.FC<StatusChartProps> = ({ data }) => {
  const chartData = [
    { name: "OPEN", count: data["OPEN"] || 0, color: "var(--color-danger)" },
    { name: "ACKNOWLEDGED", count: data["ACKNOWLEDGED"] || 0, color: "var(--color-warning)" },
    { name: "RESOLVED", count: data["RESOLVED"] || 0, color: "var(--color-success)" },
  ];

  return (
    <div className="card">
      <div className="card-title">Alerts by Status</div>
      <div style={{ height: "200px", width: "100%", marginTop: "0.5rem" }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <XAxis dataKey="name" tick={{ fontSize: 12, fill: "var(--color-text-muted)" }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: "var(--color-text-muted)" }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--color-surface)",
                borderColor: "var(--color-border)",
                color: "var(--color-text)",
                borderRadius: "var(--radius-sm)",
              }}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Accessible textual legend/summary */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-around",
          marginTop: "1rem",
          paddingTop: "0.75rem",
          borderTop: "1px solid var(--color-border)",
          fontSize: "0.8125rem",
        }}
      >
        {chartData.map((item) => (
          <div key={item.name} style={{ textAlign: "center" }}>
            <div style={{ color: "var(--color-text-muted)", fontSize: "0.75rem" }}>{item.name}</div>
            <div style={{ fontWeight: 700, fontSize: "1rem", color: item.color }}>{item.count}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

interface SeverityChartProps {
  data: Record<string, number>;
}

export const SeverityChart: React.FC<SeverityChartProps> = ({ data }) => {
  // Explicit defensive ordering: INFO < LOW < MEDIUM < HIGH < CRITICAL
  const chartData = [
    { name: "INFO", count: data["INFO"] || 0, color: "var(--color-info)" },
    { name: "LOW", count: data["LOW"] || 0, color: "var(--color-low)" },
    { name: "MEDIUM", count: data["MEDIUM"] || 0, color: "var(--color-medium)" },
    { name: "HIGH", count: data["HIGH"] || 0, color: "var(--color-high)" },
    { name: "CRITICAL", count: data["CRITICAL"] || 0, color: "var(--color-critical)" },
  ];

  return (
    <div className="card">
      <div className="card-title">Alerts by Severity</div>
      <div style={{ height: "200px", width: "100%", marginTop: "0.5rem" }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <XAxis dataKey="name" tick={{ fontSize: 12, fill: "var(--color-text-muted)" }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: "var(--color-text-muted)" }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--color-surface)",
                borderColor: "var(--color-border)",
                color: "var(--color-text)",
                borderRadius: "var(--radius-sm)",
              }}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, index) => (
                <Cell key={`sev-cell-${index}`} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Accessible textual legend/summary */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: "1rem",
          paddingTop: "0.75rem",
          borderTop: "1px solid var(--color-border)",
          fontSize: "0.8125rem",
        }}
      >
        {chartData.map((item) => (
          <div key={item.name} style={{ textAlign: "center" }}>
            <div style={{ color: "var(--color-text-muted)", fontSize: "0.7rem" }}>{item.name}</div>
            <div style={{ fontWeight: 700, fontSize: "0.9375rem", color: item.color }}>{item.count}</div>
          </div>
        ))}
      </div>
    </div>
  );
};
