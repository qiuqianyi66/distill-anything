export function boot(router: Router) {          // LINE_1
  const routes = [];                            // LINE_2
  routes.push(handlerA);                        // LINE_3
  routes.push(handlerB);                        // LINE_4
  for (const r of routes) router.add(r);        // LINE_5
  router.fallback(fallbackHandler);             // LINE_6
  return routes.length;                         // LINE_7
}                                               // LINE_8
function fallbackHandler(ctx) {                 // LINE_9
  log(ctx.path);                                // LINE_10
