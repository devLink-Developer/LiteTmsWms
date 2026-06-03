import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useGlobalTableSorting } from "./SortableTables";

function SortableTableHarness() {
  useGlobalTableSorting();

  return (
    <table>
      <thead>
        <tr>
          <th>Nombre</th>
          <th>Cantidad</th>
        </tr>
      </thead>
      <tbody data-testid="rows">
        <tr>
          <td>Zeta</td>
          <td>10 UN</td>
        </tr>
        <tr>
          <td>Alfa</td>
          <td>2 UN</td>
        </tr>
        <tr>
          <td>Cinco</td>
          <td>5 UN</td>
        </tr>
        <tr>
          <td>Ocho</td>
          <td>8,08 UN</td>
        </tr>
        <tr>
          <td>Beta</td>
          <td>25 UN</td>
        </tr>
        <tr>
          <td>Uno</td>
          <td>1 UN</td>
        </tr>
        <tr>
          <td>Mil</td>
          <td>+1.000 UN</td>
        </tr>
      </tbody>
    </table>
  );
}

function firstColumnValues() {
  return within(screen.getByTestId("rows"))
    .getAllByRole("row")
    .map((row) => within(row).getAllByRole("cell")[0].textContent);
}

function secondColumnValues() {
  return within(screen.getByTestId("rows"))
    .getAllByRole("row")
    .map((row) => within(row).getAllByRole("cell")[1].textContent);
}

describe("useGlobalTableSorting", () => {
  it("sorts any table from its headers", async () => {
    render(<SortableTableHarness />);

    const nameHeader = screen.getByRole("columnheader", { name: /Nombre/ });
    const quantityHeader = screen.getByRole("columnheader", { name: /Cantidad/ });

    await waitFor(() => expect(nameHeader).toHaveAttribute("data-sortable-table-header", "true"));

    fireEvent.click(nameHeader);
    expect(firstColumnValues()).toEqual(["Alfa", "Beta", "Cinco", "Mil", "Ocho", "Uno", "Zeta"]);
    expect(nameHeader).toHaveAttribute("aria-sort", "ascending");

    fireEvent.click(quantityHeader);
    expect(secondColumnValues()).toEqual(["1 UN", "2 UN", "5 UN", "8,08 UN", "10 UN", "25 UN", "+1.000 UN"]);

    fireEvent.click(quantityHeader);
    expect(secondColumnValues()).toEqual(["+1.000 UN", "25 UN", "10 UN", "8,08 UN", "5 UN", "2 UN", "1 UN"]);
    expect(quantityHeader).toHaveAttribute("aria-sort", "descending");
    expect(nameHeader).not.toHaveAttribute("aria-sort");
  });
});
