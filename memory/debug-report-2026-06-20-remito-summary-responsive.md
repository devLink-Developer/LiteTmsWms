# Remito Summary Responsive Panel

## Issue

On smaller expedition screens, the delivery/remito summary panel was clipped. The summary was rendered outside the panel's scrollable body as a `shrink-0` footer while the aside itself had `overflow-hidden`, so short viewports could cut off summary rows and the remito line table.

## Change

- Moved the summary into the aside's scrollable body.
- Rendered the summary before the delivery list on bottom-panel layouts, so the selected remito details are immediately visible.
- Kept the delivery list first on very wide inspector layouts.
- Converted summary fields to an auto-fitting grid.
- Wrapped the article/remito table in horizontal overflow with a stable minimum width.

## Validation

- `npm test -- --run src/features/deliveries/DeliveryExpeditionPage.test.tsx`
- `npm run build`
