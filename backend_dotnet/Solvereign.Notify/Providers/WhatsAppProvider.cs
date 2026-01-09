// =============================================================================
// SOLVEREIGN V4.1 - WhatsApp Cloud API Provider
// =============================================================================

using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Options;
using Solvereign.Notify.Models;

namespace Solvereign.Notify.Providers;

/// <summary>
/// WhatsApp Cloud API provider using Meta Business API.
/// </summary>
public sealed partial class WhatsAppProvider : INotificationProvider
{
    private readonly HttpClient _httpClient;
    private readonly WhatsAppConfig _config;
    private readonly ILogger<WhatsAppProvider> _logger;
    private readonly string _baseUrl;

    public string ProviderName => "WHATSAPP";

    public WhatsAppProvider(
        HttpClient httpClient,
        IOptions<WhatsAppConfig> config,
        ILogger<WhatsAppProvider> logger)
    {
        _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        _config = config?.Value ?? throw new ArgumentNullException(nameof(config));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        _baseUrl = $"https://graph.facebook.com/{_config.ApiVersion}";
    }

    public bool ValidateRecipient(string recipient)
    {
        if (string.IsNullOrWhiteSpace(recipient)) return false;

        // Remove formatting and validate
        var cleaned = CleanPhoneNumber(recipient);
        return cleaned.Length >= 7 && cleaned.Length <= 15 && PhoneRegex().IsMatch(cleaned);
    }

    public async Task<SendResult> SendAsync(
        string recipient,
        string templateName,
        Dictionary<string, object> templateParams,
        string? portalUrl,
        CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(_config.PhoneNumberId) || string.IsNullOrEmpty(_config.AccessToken))
        {
            return SendResult.PermanentError(ErrorCodes.ProviderAuthError, "WhatsApp not configured");
        }

        if (!ValidateRecipient(recipient))
        {
            return SendResult.PermanentError(ErrorCodes.ProviderInvalidRecipient);
        }

        var phone = CleanPhoneNumber(recipient);

        // Build template components
        var components = BuildTemplateComponents(templateParams, portalUrl);

        var payload = new
        {
            messaging_product = "whatsapp",
            to = phone,
            type = "template",
            template = new
            {
                name = templateName,
                language = new { code = templateParams.GetValueOrDefault("language", "de") },
                components
            }
        };

        var url = $"{_baseUrl}/{_config.PhoneNumberId}/messages";
        var request = new HttpRequestMessage(HttpMethod.Post, url)
        {
            Content = new StringContent(
                JsonSerializer.Serialize(payload),
                Encoding.UTF8,
                "application/json")
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _config.AccessToken);

        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(_config.TimeoutSeconds));

            var response = await _httpClient.SendAsync(request, cts.Token);
            var responseBody = await response.Content.ReadAsStringAsync(cts.Token);

            if (response.IsSuccessStatusCode)
            {
                var result = JsonSerializer.Deserialize<WhatsAppResponse>(responseBody);
                var messageId = result?.messages?.FirstOrDefault()?.id ?? "";

                _logger.LogDebug(
                    "WhatsApp message sent. MessageId: {MessageId}, Template: {Template}",
                    messageId, templateName);

                return SendResult.Ok(messageId, "SENT");
            }

            // Parse error response
            var error = TryParseError(responseBody);

            _logger.LogWarning(
                "WhatsApp send failed. StatusCode: {StatusCode}, ErrorCode: {ErrorCode}",
                response.StatusCode, error.code);

            return response.StatusCode switch
            {
                HttpStatusCode.TooManyRequests => SendResult.TransientError(
                    ErrorCodes.Provider429,
                    error.message,
                    GetRetryAfter(response)),

                HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden =>
                    SendResult.PermanentError(ErrorCodes.ProviderAuthError, error.message),

                HttpStatusCode.BadRequest when IsTemplateError(error.code) =>
                    SendResult.PermanentError(ErrorCodes.ProviderTemplateError, error.message),

                HttpStatusCode.BadRequest when IsInvalidRecipientError(error.code) =>
                    SendResult.PermanentError(ErrorCodes.ProviderInvalidRecipient, error.message),

                >= HttpStatusCode.InternalServerError =>
                    SendResult.TransientError(ErrorCodes.Provider5xx, error.message),

                _ => SendResult.TransientError(ErrorCodes.NetworkError, error.message)
            };
        }
        catch (TaskCanceledException) when (ct.IsCancellationRequested)
        {
            throw;
        }
        catch (TaskCanceledException)
        {
            _logger.LogWarning("WhatsApp request timed out");
            return SendResult.TransientError(ErrorCodes.ProviderTimeout);
        }
        catch (HttpRequestException ex)
        {
            _logger.LogError(ex, "WhatsApp request failed");
            return SendResult.TransientError(ErrorCodes.NetworkError);
        }
    }

    public async Task<bool> IsHealthyAsync(CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(_config.PhoneNumberId) || string.IsNullOrEmpty(_config.AccessToken))
            return false;

        try
        {
            var url = $"{_baseUrl}/{_config.PhoneNumberId}";
            var request = new HttpRequestMessage(HttpMethod.Get, url);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _config.AccessToken);

            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(10));

            var response = await _httpClient.SendAsync(request, cts.Token);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    private static string CleanPhoneNumber(string phone)
    {
        return phone.Replace("+", "").Replace(" ", "").Replace("-", "").Replace("(", "").Replace(")", "");
    }

    private static object[] BuildTemplateComponents(Dictionary<string, object> templateParams, string? portalUrl)
    {
        var components = new List<object>();

        // Body parameters
        var bodyParams = new List<object>();

        if (templateParams.TryGetValue("driver_name", out var driverName))
        {
            bodyParams.Add(new { type = "text", text = driverName?.ToString() ?? "" });
        }

        if (!string.IsNullOrEmpty(portalUrl))
        {
            bodyParams.Add(new { type = "text", text = portalUrl });
        }

        if (bodyParams.Count > 0)
        {
            components.Add(new
            {
                type = "body",
                parameters = bodyParams.ToArray()
            });
        }

        // Button parameters (for CTA templates)
        if (!string.IsNullOrEmpty(portalUrl))
        {
            components.Add(new
            {
                type = "button",
                sub_type = "url",
                index = 0,
                parameters = new[] { new { type = "text", text = ExtractUrlSuffix(portalUrl) } }
            });
        }

        return components.ToArray();
    }

    private static string ExtractUrlSuffix(string url)
    {
        // Extract dynamic part of URL for button parameter
        // e.g., "https://portal.example.com/plan?t=abc123" -> "abc123"
        var queryStart = url.LastIndexOf("t=", StringComparison.Ordinal);
        if (queryStart >= 0)
        {
            return url[(queryStart + 2)..];
        }
        return url;
    }

    private static (int code, string message) TryParseError(string body)
    {
        try
        {
            var doc = JsonDocument.Parse(body);
            var error = doc.RootElement.GetProperty("error");
            return (
                error.GetProperty("code").GetInt32(),
                error.GetProperty("message").GetString() ?? "Unknown error"
            );
        }
        catch
        {
            return (0, "Unknown error");
        }
    }

    private static bool IsTemplateError(int code) => code is 132000 or 132001 or 132005;
    private static bool IsInvalidRecipientError(int code) => code is 131049 or 131051;

    private static TimeSpan? GetRetryAfter(HttpResponseMessage response)
    {
        if (response.Headers.RetryAfter?.Delta is { } delta)
            return delta;
        return TimeSpan.FromMinutes(1);
    }

    [GeneratedRegex(@"^\d+$")]
    private static partial Regex PhoneRegex();

    private sealed class WhatsAppResponse
    {
        public WhatsAppMessage[]? messages { get; set; }
    }

    private sealed class WhatsAppMessage
    {
        public string? id { get; set; }
    }
}
