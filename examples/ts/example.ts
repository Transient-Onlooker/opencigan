import { OpensiganClient, OpensiganError } from '../../clients/ts/index.ts';

async function main() {
  const client = new OpensiganClient({
    baseUrl: process.env.OPENCIGAN_API_BASE_URL || 'http://127.0.0.1:8000',
    timeoutMs: 10000,
  });
  const query = process.argv[2] || '봄빛';
  const kst = new Date(Date.now() + 9 * 60 * 60 * 1000);
  const today = kst.toISOString().slice(0, 10);
  kst.setUTCDate(kst.getUTCDate() - (kst.getUTCDay() + 6) % 7);
  const monday = kst.toISOString().slice(0, 10);

  console.log('Process:', await client.getStatus());
  const { schools } = await client.searchSchools(query);
  console.log('Comcigan schools:', schools);
  if (schools.length) {
    const school = schools[0].id;
    console.log('Timetable:', await client.getTimetable(school, monday, { grade: 1, class: 1 }));
    console.log('Calendar URL:', client.getTimetableIcsUrl(school, 1, 1, { weeks: 2, mode: 'periods' }));
    try {
      console.log('History first page:', await client.getTimetableHistory(school, monday));
    } catch (error) {
      if (!(error instanceof OpensiganError) || error.code !== 'history_disabled') throw error;
      console.log('History is disabled on this server.');
    }
  }

  const neis = await client.searchNeisSchools(query);
  console.log('NEIS schools (confirm the match before using the ID):', neis.schools);
  if (neis.schools.length) {
    console.log('Meals for first NEIS result:', await client.getMeals(neis.schools[0].id, today, today));
  }
}

main().catch((error) => {
  if (error instanceof OpensiganError) {
    console.error('API request failed:', error.status, error.code,
      { isTimeout: error.isTimeout, isNetworkError: error.isNetworkError });
  } else {
    console.error('Example failed.');
  }
  process.exitCode = 1;
});
