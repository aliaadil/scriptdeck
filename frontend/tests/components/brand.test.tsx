import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { Brand, BrandLogo, BrandMark, BrandSidebar } from '@/components/brand';

describe('Brand', () => {
  it('renders a link to the dashboard with an accessible name', () => {
    render(
      <MemoryRouter>
        <Brand />
      </MemoryRouter>,
    );
    const link = screen.getByRole('link', { name: /kindling/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/kindling/dashboard');
  });

  it('renders the combined mark + wordmark in the sidebar (wordmark visible)', () => {
    // The sidebar variant includes the wordmark so the brand is identifiable
    // at a glance. The image carries alt="Kindling" and the link carries an
    // aria-label — they match.
    render(
      <MemoryRouter>
        <Brand />
      </MemoryRouter>,
    );
    const img = screen.getByRole('img', { name: /kindling/i });
    expect(img).toBeInTheDocument();
    expect(img.getAttribute('src')).toMatch(/logo-sidebar\.svg$/);
  });
});

describe('BrandLogo', () => {
  it('renders the full lockup (mark + wordmark + tagline) for auth screens', () => {
    render(<BrandLogo size="lg" />);
    const img = screen.getByRole('img', { name: /kindling/i });
    expect(img).toBeInTheDocument();
    expect(img.getAttribute('src')).toMatch(/logo\.svg$/);
  });
});

describe('BrandSidebar', () => {
  it('renders the compact lockup with a configurable height', () => {
    render(<BrandSidebar height={32} />);
    const img = screen.getByRole('img', { name: /kindling/i });
    expect(img).toBeInTheDocument();
    expect(img.getAttribute('src')).toMatch(/logo-sidebar\.svg$/);
    expect(img).toHaveStyle({ height: '32px' });
  });
});

describe('BrandMark', () => {
  it('renders just the mark, decorative (no accessible name)', () => {
    render(<BrandMark size={32} />);
    const img = screen.getByRole('img');
    expect(img).not.toHaveAccessibleName();
  });
});