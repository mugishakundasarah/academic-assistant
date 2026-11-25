import NextLink from "next/link";

import { EmptyState } from "./components/ui";

export default function NotFound() {
  return (
    <div className="page">
      <header className="page-head">
        <h1>Not found</h1>
      </header>
      <EmptyState title="This page or course doesn’t exist">
        <p>
          It may not have been synced yet. <NextLink href="/">Back to Today</NextLink>
        </p>
      </EmptyState>
    </div>
  );
}
