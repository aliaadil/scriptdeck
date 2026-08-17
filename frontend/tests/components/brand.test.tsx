import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { Brand, BrandLogo, BrandMark } from '@/components/brand';

describe('Brand', () => {
  it('renders a link with an accessible name', () => {
    render(
      <MemoryRouter>
        <Brand />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /kindling/i })).toBeInTheDocument();
  });

  it('does not render a visible wordmark (mark-only in the sidebar)', () => {
    // The wordmark is illegible at sidebar height; the brand link uses the
    // mark image only and exposes the name via aria-label.
    render(
      <MemoryRouter>
        <Brand />
      </MemoryRouter>,
    );
    // The wordmark would render as an <img> with alt="Kindling"; the mark
    // uses alt="" (decorative). Confirm only one image is in the tree.
    const images = screen.getAllByRole('img');
    expect(images).toHaveLength(1);
    expect(images[0]).not.toHaveAccessibleName(/kindling/i);
  });
});

describe('BrandLogo', () => {
  it('renders the combined mark + wordmark image', () => {
    render(<BrandLogo size="lg" />);
    const img = screen.getByRole('img', { name: /kindling/i });
    expect(img).toBeInTheDocument();
  });
});

describe('BrandMark', () => {
  it('renders just the mark, decorative (no accessible name)', () => {
    render(<BrandMark size={32} />);
    const img = screen.getByRole('img');
    expect(img).not.toHaveAccessibleName();
  });
});
