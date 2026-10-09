import { useState } from "react";

/** A button that asks "are you sure?" inline before running ``onConfirm``. */
export function ConfirmButton({
  label,
  question,
  confirmLabel = "Delete",
  onConfirm,
  className = "ib",
  children,
}: {
  label: string;
  question: string;
  confirmLabel?: string;
  onConfirm: () => void;
  className?: string;
  children?: React.ReactNode;
}) {
  const [asking, setAsking] = useState(false);
  if (asking)
    return (
      <span className="confirm" role="group" aria-label={question}>
        <span>{question}</span>
        <button
          type="button"
          className="btn danger"
          onClick={(e) => {
            e.stopPropagation();
            setAsking(false);
            onConfirm();
          }}
        >
          {confirmLabel}
        </button>
        <button
          type="button"
          className="btn"
          onClick={(e) => {
            e.stopPropagation();
            setAsking(false);
          }}
        >
          Cancel
        </button>
      </span>
    );
  return (
    <button
      type="button"
      className={className}
      aria-label={label}
      title={label}
      onClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
        setAsking(true);
      }}
    >
      {children ?? label}
    </button>
  );
}
