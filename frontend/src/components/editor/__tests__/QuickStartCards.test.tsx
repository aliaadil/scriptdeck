import { render, screen, fireEvent } from "@testing-library/react";
import { QuickStartCards } from "../QuickStartCards";

it("renders three cards and fires onPick", () => {
  const onPick = vi.fn();
  render(<QuickStartCards onPick={onPick} />);
  expect(screen.getByText(/Python/i)).toBeInTheDocument();
  expect(screen.getByText(/Node/i)).toBeInTheDocument();
  expect(screen.getByText(/Bash/i)).toBeInTheDocument();
  fireEvent.click(screen.getByText(/Python/i));
  expect(onPick).toHaveBeenCalledWith("python");
});