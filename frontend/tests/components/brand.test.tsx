import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { Brand } from '@/components/brand';

function renderBrand(collapsed: boolean) {
  return render(
    <MemoryRouter>
      <Brand collapsed={collapsed} />
    </MemoryRouter>,
  );
}

describe('Brand', () => {
  it('exposes an accessible name when expanded', () => {
    renderBrand(false);
    expect(screen.getByRole('link', { name: /kindling/i })).toBeInTheDocument();
  });

  it('exposes an accessible name when collapsed to the mark only', () => {
    renderBrand(true);
    // The mark is decorative (alt=""), so without an explicit label the link
    // would be announced as just "link" with no destination.
    expect(screen.getByRole('link', { name: /kindling/i })).toBeInTheDocument();
  });

  it('does not render the retired Kindling name', () => {
    renderBrand(false);
    expect(screen.queryByText(/kindling/i)).not.toBeInTheDocument();
  });
});
