// Setup type definitions for built-in Supabase Runtime APIs
import "jsr:@supabase/functions-js/edge-runtime.d.ts";

// Import AWS App Runner client from AWS SDK v3
import { AppRunnerClient, ResumeServiceCommand } from "npm:@aws-sdk/client-apprunner";

// Read configuration from environment
const REGION = Deno.env.get("AWS_REGION") ?? "eu-west-2";
const SERVICE_ARN = Deno.env.get("APP_RUNNER_SERVICE_ARN")!;

// Initialize the App Runner client with credentials from environment
const client = new AppRunnerClient({
    region: REGION,
    credentials: {
        accessKeyId: Deno.env.get("AWS_ACCESS_KEY_ID")!,
        secretAccessKey: Deno.env.get("AWS_SECRET_ACCESS_KEY")!,
        sessionToken: Deno.env.get("AWS_SESSION_TOKEN") || undefined,
    },
});

console.info('Supabase App Runner resume function started');

// Handle incoming requests
Deno.serve(async (req: Request) => {
    try {
        // Trigger the ResumeService operation
        const response = await client.send(
            new ResumeServiceCommand({ ServiceArn: SERVICE_ARN })
        );

        // Return the operation ID to the caller
        return new Response(
            JSON.stringify({ OperationId: response.OperationId }),
            {
                status: 200,
                headers: { 'Content-Type': 'application/json', 'Connection': 'keep-alive' },
            }
        );
    } catch (err) {
        console.error('Error resuming App Runner service:', err);
        return new Response(
            JSON.stringify({ error: (err as Error).message }),
            { status: 500, headers: { 'Content-Type': 'application/json' } }
        );
    }
});
