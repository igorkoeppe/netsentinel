import React from "react";

interface CardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ReactNode;
  accentColor?: string;
}

export const Card: React.FC<CardProps> = ({
  title,
  value,
  subtitle,
  icon,
  accentColor,
}) => {
  return (
    <div
      className="card"
      style={{
        borderLeft: accentColor ? `4px solid ${accentColor}` : undefined,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="card-title">{title}</div>
          <div className="card-value">{value}</div>
          {subtitle && (
            <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "0.25rem" }}>
              {subtitle}
            </div>
          )}
        </div>
        {icon && (
          <div style={{ color: accentColor || "var(--color-text-muted)", opacity: 0.85 }}>
            {icon}
          </div>
        )}
      </div>
    </div>
  );
};
