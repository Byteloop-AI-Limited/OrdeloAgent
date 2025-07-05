// supabase/functions/app-runner-manager/index.ts
import { serve } from "https://deno.land/std@0.190.0/http/server.ts";
import { AppRunnerClient, PauseServiceCommand, ResumeServiceCommand } from "npm:@aws-sdk/client-apprunner";
// Read configuration from environment
const REGION = Deno.env.get("AWS_REGION") ?? "eu-west-2";
const SERVICE_ARN = Deno.env.get("APP_RUNNER_SERVICE_ARN");
// Initialize the App Runner client
const client = new AppRunnerClient({
    region: REGION,
    credentials: {
        accessKeyId: Deno.env.get("AWS_ACCESS_KEY_ID"),
        secretAccessKey: Deno.env.get("AWS_SECRET_ACCESS_KEY"),
        sessionToken: Deno.env.get("AWS_SESSION_TOKEN") || undefined
    }
});
console.info('App Runner manager function started');
serve(async (req) => {
    const url = new URL(req.url);
    // Extract action from the last path segment
    const segments = url.pathname.split('/').filter(Boolean);
    const action = segments[segments.length - 1];
    let command;
    if (action === 'pause') {
        command = new PauseServiceCommand({
            ServiceArn: SERVICE_ARN
        });
    } else if (action === 'resume') {
        command = new ResumeServiceCommand({
            ServiceArn: SERVICE_ARN
        });
    } else {
        return new Response(JSON.stringify({
            error: "Not Found"
        }), {
            status: 404,
            headers: {
                'content-type': 'application/json'
            }
        });
    }
    try {
        const { OperationId } = await client.send(command);
        return new Response(JSON.stringify({
            OperationId
        }), {
            status: 200,
            headers: {
                'content-type': 'application/json'
            }
        });
    } catch (err) {
        console.error('Error executing', action, err);
        return new Response(JSON.stringify({
            error: err.message
        }), {
            status: 500,
            headers: {
                'content-type': 'application/json'
            }
        });
    }
});

/*

https://pqsvhidiwiydgshynfib.supabase.co/functions/v1/app-runner-manager/resume

https://pqsvhidiwiydgshynfib.supabase.co/functions/v1/app-runner-manager/pause

  */
