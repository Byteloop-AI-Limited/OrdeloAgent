// Setup type definitions for built-in Supabase Runtime APIs
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from 'npm:@supabase/supabase-js@2'

Deno.serve(async (req) => {
    try {
        const supabase = createClient(
            Deno.env.get('SUPABASE_URL') ?? '',
            Deno.env.get('SUPABASE_ANON_KEY') ?? '',
            { db: { schema: 'pgmq_public' } },
            { global: { headers: { Authorization: req.headers.get('Authorization')! } } }
        )
        const json = await req.json();

        const { data, error } = await supabase.rpc('send', {
            queue_name: 'owntracks',
            message: json,
        })
        if (error) {
            console.info(`Failed to send message to queue 'owntracks': ${error.message}`);
            throw error
        }

        console.info(`Successfully sent message to queue 'owntracks' with ID: ${data}`);

        return new Response(JSON.stringify({ data }), {
            headers: { 'Content-Type': 'application/json' },
            status: 200,
        })
    } catch (err) {
        console.info(`Error processing request: ${err?.message ?? err}`);
        return new Response(String(err?.message ?? err), { status: 500 })
    }
})