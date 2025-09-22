import { PropsWithChildren } from "react";

interface SectionCardProps extends PropsWithChildren {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  id?: string;
}

export function SectionCard({ title, description, actions, id, children }: SectionCardProps) {
  return (
    <section className="section-card" id={id}>
      <header>
        <div>
          <h2>{title}</h2>
          {description && <p className="muted">{description}</p>}
        </div>
        {actions && <div className="actions">{actions}</div>}
      </header>
      <div className="section-body">{children}</div>
    </section>
  );
}
