// https://pqsvhidiwiydgshynfib.supabase.co/functions/v1/app-runner-manager/ordelo/pause


// supabase/functions/app-runner-manager/index.ts
import { serve } from "https://deno.land/std@0.190.0/http/server.ts";
import { AppRunnerClient, PauseServiceCommand, ResumeServiceCommand } from "npm:@aws-sdk/client-apprunner";
// Read configuration from environment
const REGION = Deno.env.get("AWS_REGION") ?? "eu-west-2";
const client = new AppRunnerClient({
    region: REGION,
    credentials: {
        accessKeyId: Deno.env.get("AWS_ACCESS_KEY_ID"),
        secretAccessKey: Deno.env.get("AWS_SECRET_ACCESS_KEY"),
        sessionToken: Deno.env.get("AWS_SESSION_TOKEN") || undefined
    }
});
console.info("App Runner manager function started");
serve(async (req) => {
    const url = new URL(req.url);
    const segments = url.pathname.split('/').filter(Boolean);
    // Grab from the end:
    const action = segments.pop();
    const serviceKey = segments.pop();
    if (!serviceKey || !action) {
        return new Response(JSON.stringify({
            error: "Invalid path. Use /{service}/[pause|resume]"
        }), {
            status: 404,
            headers: {
                "content-type": "application/json"
            }
        });
    }
    // Build the env var name dynamically
    const envVarName = serviceKey.toUpperCase().replace(/[^A-Z0-9]/g, "_") + "_APP_RUNNER_SERVICE_ARN";
    const serviceArn = Deno.env.get(envVarName);
    if (!serviceArn) {
        return new Response(JSON.stringify({
            error: `Environment variable ${envVarName} is not set`
        }), {
            status: 400,
            headers: {
                "content-type": "application/json"
            }
        });
    }
    let command;
    if (action === "pause") {
        command = new PauseServiceCommand({
            ServiceArn: serviceArn
        });
    } else if (action === "resume") {
        command = new ResumeServiceCommand({
            ServiceArn: serviceArn
        });
    } else {
        return new Response(JSON.stringify({
            error: "Action not recognized. Use 'pause' or 'resume'."
        }), {
            status: 404,
            headers: {
                "content-type": "application/json"
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
                "content-type": "application/json"
            }
        });
    } catch (err) {
        console.error("Error executing", action, err);
        return new Response(JSON.stringify({
            error: err.message
        }), {
            status: 500,
            headers: {
                "content-type": "application/json"
            }
        });
    }
});
