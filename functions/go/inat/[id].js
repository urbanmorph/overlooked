// /go/inat/<id>: the link from the shortlist page to an observation on iNaturalist (a 302 redirect).
// It only checks the id. _middleware.js counts the visit (dim inat_out, key = ?g=, see lib/metrics.js),
// after the redirect is ready, so a metrics failure cannot change or delay it.

const ID = /^[1-9]\d{0,11}$/;   // iNaturalist observation id

export function onRequest({ params }) {
  const id = String(params.id ?? '');
  if (!ID.test(id)) return new Response('Not found', { status: 404 });
  return Response.redirect(`https://www.inaturalist.org/observations/${id}`, 302);
}
