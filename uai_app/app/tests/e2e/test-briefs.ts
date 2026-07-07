import { assert, connectHarness } from './test-harness';

export async function run(): Promise<void> {
  const h = await connectHarness();
  try {
    const briefInfo = await h.js<{ count: number; names: string[] }>(`window.uai.briefs.list().then((items) => ({
      count: items.length,
      names: items.slice(0, 5).map((item) => item.display_name || item.name || item.entity_id),
    }))`);
    assert(briefInfo.count > 0, 'Briefs API returned no items');
    assert(briefInfo.names.length > 0, 'Briefs API did not provide any names');
  } finally {
    await h.close();
  }
}
