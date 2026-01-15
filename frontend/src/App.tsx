import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import {
  Badge,
  Box,
  Button,
  Container,
  FormControl,
  FormLabel,
  Grid,
  GridItem,
  Heading,
  HStack,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  SimpleGrid,
  Stack,
  Text,
  useToast,
  VStack
} from "@chakra-ui/react";
import { ApiError, downloadResult, getJobStatus, startLegacyPipeline } from "./lib/api";
import { keyframes } from "@emotion/react";
import {
  ArrowForwardIcon,
  AttachmentIcon,
  CheckIcon,
  CopyIcon,
  DownloadIcon,
  EditIcon,
  RepeatIcon
} from "@chakra-ui/icons";

const STORAGE_KEY = "pipeline_jobs";
const FORM_STORAGE_KEY = "pipeline_form_defaults";

type JobRecord = {
  jobId: string;
  status: string;
  explanationName: string;
  year?: string;
  subject?: string;
  university?: string;
  author?: string;
  createdAt: string;
  updatedAt: string;
  message?: string;
  error?: string;
};

const statusLabels: Record<string, string> = {
  accepted: "受付済み",
  queued: "受付済み",
  generating_md: "解答作成中",
  generating_pdf: "PDF変換中",
  done: "完了",
  failed: "失敗",
  failed_to_convert: "PDF変換失敗",
  expired: "期限切れ"
};

const statusBadgeStyles: Record<string, { bg: string; color: string }> = {
  accepted: { bg: "#F8E9C6", color: "#6D5F4B" },
  queued: { bg: "#F8E9C6", color: "#6D5F4B" },
  generating_md: { bg: "#FBE7B3", color: "#6D5F4B" },
  generating_pdf: { bg: "#FBE1A1", color: "#6D5F4B" },
  done: { bg: "#E6F4DD", color: "#2B593F" },
  failed: { bg: "#F7D6D2", color: "#7C2E2E" },
  failed_to_convert: { bg: "#F2E0C8", color: "#6D5F4B" },
  expired: { bg: "#EFE7DA", color: "#6D5F4B" }
};

const pendingStatuses = [
  "accepted",
  "queued",
  "generating_md",
  "generating_pdf",
  "processing",
  "running",
  "converting"
];

const MAX_TEXT_LENGTH = 100;
const MAX_FILE_SIZE = 20 * 1024 * 1024;

const etaLabels: Record<string, string> = {
  queued: "残り20分程度",
  generating_md: "残り15分程度",
  generating_pdf: "残り1分未満"
};

function loadJobs(): JobRecord[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as JobRecord[];
  } catch {
    return [];
  }
}

function saveJobs(jobs: JobRecord[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
}

type FormDefaults = {
  year: string;
  subject: string;
  university: string;
  author: string;
  explanationName: string;
};

function loadFormDefaults(): Partial<FormDefaults> {
  try {
    const raw = localStorage.getItem(FORM_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    return parsed as Partial<FormDefaults>;
  } catch {
    return {};
  }
}

function saveFormDefaults(values: FormDefaults) {
  localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(values));
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ja-JP");
}

type StatusResult = {
  jobId: string;
  data?: { status?: string; message?: string; error?: string };
  error?: unknown;
};

function mergeStatusResults(prev: JobRecord[], results: StatusResult[]) {
  const now = new Date().toISOString();
  return prev.map((job) => {
    const match = results.find((item) => item.jobId === job.jobId);
    if (!match) return job;
    if (match.error) {
      if (match.error instanceof ApiError && [404, 410].includes(match.error.status)) {
        return {
          ...job,
          status: "expired",
          updatedAt: now,
          error: match.error.message
        };
      }
      return {
        ...job,
        updatedAt: now,
        error: match.error instanceof Error ? match.error.message : "Unknown error"
      };
    }
    if (!match.data) {
      return job;
    }
    return {
      ...job,
      status: match.data.status ?? job.status,
      message: match.data.message,
      error: match.data.error,
      updatedAt: now
    };
  });
}

export default function App() {
  const defaults = loadFormDefaults();
  const [apiKey, setApiKey] = useState("");
  const [year, setYear] = useState(defaults.year ?? "");
  const [subject, setSubject] = useState(defaults.subject ?? "");
  const [university, setUniversity] = useState(defaults.university ?? "");
  const [author, setAuthor] = useState(defaults.author ?? "");
  const [explanationName, setExplanationName] = useState(defaults.explanationName ?? "");
  const [userEditedName, setUserEditedName] = useState(false);
  const [inputFile, setInputFile] = useState<File | null>(null);
  const toast = useToast();
  const [jobs, setJobs] = useState<JobRecord[]>(() => loadJobs());
  const [downloadingJobId, setDownloadingJobId] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isRefreshCooldown, setIsRefreshCooldown] = useState(false);
  const [retryJob, setRetryJob] = useState<JobRecord | null>(null);
  const [retryApiKey, setRetryApiKey] = useState("");
  const [retryYear, setRetryYear] = useState("");
  const [retrySubject, setRetrySubject] = useState("");
  const [retryUniversity, setRetryUniversity] = useState("");
  const [retryAuthor, setRetryAuthor] = useState("");
  const [retryExplanationName, setRetryExplanationName] = useState("");
  const [retryUserEditedName, setRetryUserEditedName] = useState(false);
  const [retryFile, setRetryFile] = useState<File | null>(null);
  const [isRetryOpen, setIsRetryOpen] = useState(false);
  const [isNoticeOpen, setIsNoticeOpen] = useState(false);
  const [noticeJobId, setNoticeJobId] = useState<string | null>(null);
  const [searchJobId, setSearchJobId] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const pollingRef = useRef<number | null>(null);
  const refreshCooldownRef = useRef<number | null>(null);

  useEffect(() => {
    saveJobs(jobs);
  }, [jobs]);

  useEffect(() => {
    if (userEditedName) return;
    if (!year && !subject) {
      setExplanationName("");
      return;
    }
    const yearLabel = year ? `${year}年度` : "";
    const base = [yearLabel, subject].filter(Boolean).join("_");
    setExplanationName(`${base}_解答解説`);
  }, [year, subject, userEditedName]);

  useEffect(() => {
    saveFormDefaults({
      year: year.trim(),
      subject: subject.trim(),
      university: university.trim(),
      author: author.trim(),
      explanationName: explanationName.trim()
    });
  }, [year, subject, university, author, explanationName]);

  useEffect(() => {
    if (!isRetryOpen) return;
    if (retryUserEditedName) return;
    if (!retryYear && !retrySubject) {
      setRetryExplanationName("");
      return;
    }
    const yearLabel = retryYear ? `${retryYear}年度` : "";
    const base = [yearLabel, retrySubject].filter(Boolean).join("_");
    setRetryExplanationName(`${base}_解答解説`);
  }, [retryYear, retrySubject, retryUserEditedName, isRetryOpen]);

  const pendingJobs = useMemo(
    () =>
      jobs.filter((job) => pendingStatuses.includes(job.status)),
    [jobs]
  );

  const showToast = (title: string, status: "info" | "success" | "warning" | "error") => {
    toast({
      title,
      status,
      duration: 5000,
      isClosable: true,
      position: "top"
    });
  };

  const validateTextInputs = (values: {
    explanationName: string;
    year: string;
    subject: string;
    university: string;
    author: string;
  }) => {
    if (!/^\d{1,4}$/.test(values.year.trim())) {
      showToast("年度は1〜4桁の数字で入力してください。", "warning");
      return false;
    }
    const overLimit = Object.entries(values).find(
      ([key, value]) => key !== "year" && value.trim().length > MAX_TEXT_LENGTH
    );
    if (overLimit) {
      showToast("各項目は100文字以内で入力してください。", "warning");
      return false;
    }
    return true;
  };

  const handleFileChange = (
    event: ChangeEvent<HTMLInputElement>,
    setFile: (file: File | null) => void
  ) => {
    const file = event.target.files?.[0] ?? null;
    if (!file) {
      setFile(null);
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      showToast("ファイルサイズは20MB以下にしてください。", "warning");
      event.target.value = "";
      setFile(null);
      return;
    }
    setFile(file);
  };

  const refreshPendingJobs = async () => {
    const targets = jobs.filter((job) => pendingStatuses.includes(job.status));
    if (targets.length === 0) {
      showToast("更新する待機中ジョブがありません。", "info");
      return;
    }
    setIsRefreshing(true);
    const results = await Promise.all(
      targets.map(async (job) => {
        try {
          const data = await getJobStatus(job.jobId);
          return { jobId: job.jobId, data };
        } catch (error) {
          return { jobId: job.jobId, error };
        }
      })
    );
    setJobs((prev) => mergeStatusResults(prev, results));
    setIsRefreshing(false);
    showToast("ステータスを更新しました。", "success");
  };

  const handleRefreshClick = async () => {
    if (isRefreshing || isRefreshCooldown) return;
    setIsRefreshCooldown(true);
    await refreshPendingJobs();
    refreshCooldownRef.current = window.setTimeout(() => {
      setIsRefreshCooldown(false);
    }, 10000);
  };

  useEffect(() => {
    return () => {
      if (refreshCooldownRef.current) {
        window.clearTimeout(refreshCooldownRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (pendingJobs.length === 0) return;
    if (pollingRef.current) {
      window.clearTimeout(pollingRef.current);
    }
    const controller = new AbortController();

    pollingRef.current = window.setTimeout(async () => {
      const results = await Promise.all(
        pendingJobs.map(async (job) => {
          try {
            const data = await getJobStatus(job.jobId, controller.signal);
            return { jobId: job.jobId, data };
          } catch (error) {
            return { jobId: job.jobId, error };
          }
        })
      );

      setJobs((prev) => mergeStatusResults(prev, results));
    }, 10000);

    return () => {
      controller.abort();
      if (pollingRef.current) {
        window.clearTimeout(pollingRef.current);
      }
    };
  }, [pendingJobs]);

  const canSubmit =
    explanationName.trim() &&
    year.trim() &&
    subject.trim() &&
    university.trim() &&
    author.trim() &&
    inputFile;

  const retryCanSubmit =
    retryExplanationName.trim() &&
    retryYear.trim() &&
    retrySubject.trim() &&
    retryUniversity.trim() &&
    retryAuthor.trim() &&
    retryFile;

  const onSubmit = async () => {
    if (!inputFile || !canSubmit) {
      showToast("必須項目を入力し、ファイルを選択してください。", "warning");
      return;
    }
    if (
      !validateTextInputs({
        explanationName,
        year,
        subject,
        university,
        author
      })
    ) {
      return;
    }

    try {
      const res = await startLegacyPipeline({
        apiKey: apiKey.trim() || undefined,
        file: inputFile,
        explanationName: explanationName.trim(),
        university: university.trim(),
        year: year.trim(),
        subject: subject.trim(),
        author: author.trim()
      });

      const now = new Date().toISOString();
      const job: JobRecord = {
        jobId: res.job_id,
        status: res.status ?? "queued",
        explanationName: explanationName.trim(),
        year: year.trim(),
        subject: subject.trim(),
        university: university.trim(),
        author: author.trim(),
        createdAt: now,
        updatedAt: now,
        message: res.message
      };

      saveFormDefaults({
        year: year.trim(),
        subject: subject.trim(),
        university: university.trim(),
        author: author.trim(),
        explanationName: explanationName.trim()
      });
      setJobs((prev) => [job, ...prev]);
      showToast("ジョブを受付しました。完了までお待ちください。", "success");
      setNoticeJobId(res.job_id);
      setIsNoticeOpen(true);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "送信に失敗しました。", "error");
    }
  };

  const handleDownload = async (jobId: string) => {
    setDownloadingJobId(jobId);
    try {
      await downloadResult(jobId);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setJobs((prev) =>
          prev.map((job) =>
            job.jobId === jobId
              ? {
                ...job,
                status: "failed_to_convert",
                updatedAt: new Date().toISOString(),
                error: "PDF変換に失敗しました。再試行してください。"
              }
              : job
          )
        );
        showToast("PDF変換に失敗しました。再試行してください。", "error");
      } else {
        showToast(error instanceof Error ? error.message : "ダウンロードに失敗しました。", "error");
      }
    } finally {
      setDownloadingJobId(null);
    }
  };

  const openRetryModal = (job: JobRecord) => {
    const stored = loadFormDefaults();
    setRetryJob(job);
    setRetryApiKey("");
    setRetryYear(job.year ?? stored.year ?? "");
    setRetrySubject(job.subject ?? stored.subject ?? "");
    setRetryUniversity(job.university ?? stored.university ?? "");
    setRetryAuthor(job.author ?? stored.author ?? "");
    setRetryExplanationName(job.explanationName || stored.explanationName || "");
    setRetryUserEditedName(Boolean(job.explanationName || stored.explanationName));
    setRetryFile(null);
    setIsRetryOpen(true);
  };

  const closeRetryModal = () => {
    setIsRetryOpen(false);
    setRetryJob(null);
    setRetryFile(null);
  };

  const handleCopyJobId = async () => {
    if (!noticeJobId) return;
    try {
      await navigator.clipboard.writeText(noticeJobId);
      showToast("job_id をコピーしました。", "success");
    } catch {
      showToast("job_id のコピーに失敗しました。", "error");
    }
  };

  const closeNoticeModal = () => {
    setIsNoticeOpen(false);
    setNoticeJobId(null);
  };

  const handleSearchJob = async () => {
    const trimmed = searchJobId.trim();
    if (!trimmed) {
      showToast("JOB_ID を入力してください。", "warning");
      return;
    }
    setIsSearching(true);
    try {
      const data = await getJobStatus(trimmed);
      const now = new Date().toISOString();
      setJobs((prev) => {
        const existing = prev.find((job) => job.jobId === trimmed);
        if (existing) {
          return prev.map((job) =>
            job.jobId === trimmed
              ? {
                ...job,
                status: data.status ?? job.status,
                message: data.message,
                error: data.error,
                updatedAt: now
              }
              : job
          );
        }
        return [
          {
            jobId: trimmed,
            status: data.status ?? "queued",
            explanationName: trimmed,
            createdAt: now,
            updatedAt: now,
            message: data.message,
            error: data.error
          },
          ...prev
        ];
      });
      showToast("ジョブを追加しました。", "success");
    } catch (error) {
      if (error instanceof ApiError && [404, 410].includes(error.status)) {
        showToast("該当するジョブが見つかりませんでした。", "error");
      } else {
        showToast(error instanceof Error ? error.message : "検索に失敗しました。", "error");
      }
    } finally {
      setIsSearching(false);
    }
  };

  const onRetrySubmit = async () => {
    if (!retryFile || !retryCanSubmit) {
      showToast("必須項目を入力し、ファイルを選択してください。", "warning");
      return;
    }
    if (
      !validateTextInputs({
        explanationName: retryExplanationName,
        year: retryYear,
        subject: retrySubject,
        university: retryUniversity,
        author: retryAuthor
      })
    ) {
      return;
    }

    try {
      const res = await startLegacyPipeline({
        apiKey: retryApiKey.trim() || undefined,
        file: retryFile,
        explanationName: retryExplanationName.trim(),
        university: retryUniversity.trim(),
        year: retryYear.trim(),
        subject: retrySubject.trim(),
        author: retryAuthor.trim()
      });

      const now = new Date().toISOString();
      const job: JobRecord = {
        jobId: res.job_id,
        status: res.status ?? "queued",
        explanationName: retryExplanationName.trim(),
        year: retryYear.trim(),
        subject: retrySubject.trim(),
        university: retryUniversity.trim(),
        author: retryAuthor.trim(),
        createdAt: now,
        updatedAt: now,
        message: res.message
      };

      saveFormDefaults({
        year: retryYear.trim(),
        subject: retrySubject.trim(),
        university: retryUniversity.trim(),
        author: retryAuthor.trim(),
        explanationName: retryExplanationName.trim()
      });

      setJobs((prev) => [job, ...prev]);
      showToast("ジョブを受付しました。完了までお待ちください。", "success");
      closeRetryModal();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "送信に失敗しました。", "error");
    }
  };

  const loadingBar = keyframes`
    0% { transform: scaleX(0); }
    100% { transform: scaleX(1); }
  `;

  const shapeShift = keyframes`
    0% { border-radius: 50%; transform: scale(1); }
    33% { border-radius: 10%; transform: scale(1.1) rotate(20deg); }
    66% { border-radius: 0%; transform: scale(0.9) rotate(-10deg); }
    100% { border-radius: 50%; transform: scale(1); }
  `;

  const noticeCheck = keyframes`
    0% { opacity: 0; transform: scale(0.8); }
    60% { opacity: 1; transform: scale(1.08); }
    100% { opacity: 1; transform: scale(1); }
  `;

  return (
    <Box minH="100dvh" pb={{ base: 10, md: 16 }} position="relative" overflow="hidden">
      {/* 複数の線形グラデーションを重ねた背景レイヤー */}
      <Box
        position="absolute"
        inset={0}
        bgGradient="linear(to-br, rgba(201, 161, 74, 0.03), rgba(139, 108, 47, 0.08), rgba(201, 161, 74, 0.05))"
        zIndex={0}
      />
      <Box
        position="absolute"
        inset={0}
        bgGradient="linear(135deg, transparent 0%, rgba(201, 161, 74, 0.06) 40%, transparent 80%)"
        zIndex={0}
      />
      <Box
        position="absolute"
        inset={0}
        bgGradient="linear(to-tr, rgba(139, 108, 47, 0.04), transparent, rgba(201, 161, 74, 0.07))"
        zIndex={0}
      />

      {/* 大きな装飾模様 */}
      <Box
        position="absolute"
        top="-120px"
        right="-120px"
        w="320px"
        h="320px"
        bgGradient="radial(circle, rgba(201, 161, 74, 0.16), rgba(139, 108, 47, 0.08))"
        filter="blur(14px)"
        borderRadius="50%"
        zIndex={0}
      />
      <Box
        position="absolute"
        bottom="-160px"
        left="-120px"
        w="360px"
        h="360px"
        bgGradient="radial(circle, rgba(139, 108, 47, 0.12), rgba(201, 161, 74, 0.06))"
        filter="blur(20px)"
        borderRadius="45%"
        zIndex={0}
      />

      {/* 追加の中型装飾模様 */}
      <Box
        position="absolute"
        top="30%"
        left="10%"
        w="220px"
        h="220px"
        bgGradient="radial(circle, rgba(201, 161, 74, 0.10), transparent)"
        filter="blur(16px)"
        borderRadius="40%"
        zIndex={0}
      />
      <Box
        position="absolute"
        top="60%"
        right="15%"
        w="180px"
        h="180px"
        bgGradient="radial(circle, rgba(139, 108, 47, 0.08), transparent)"
        filter="blur(12px)"
        borderRadius="35%"
        zIndex={0}
      />

      {/* 小さな装飾模様（散りばめる） */}
      <Box
        position="absolute"
        top="15%"
        right="25%"
        w="100px"
        h="100px"
        bgGradient="radial(circle, rgba(201, 161, 74, 0.14), transparent)"
        filter="blur(8px)"
        borderRadius="50%"
        zIndex={0}
      />
      <Box
        position="absolute"
        bottom="25%"
        left="20%"
        w="120px"
        h="120px"
        bgGradient="radial(circle, rgba(139, 108, 47, 0.10), transparent)"
        filter="blur(10px)"
        borderRadius="50%"
        zIndex={0}
      />
      <Box
        position="absolute"
        top="45%"
        right="8%"
        w="80px"
        h="80px"
        bgGradient="radial(circle, rgba(201, 161, 74, 0.12), transparent)"
        filter="blur(6px)"
        borderRadius="50%"
        zIndex={0}
      />
      <Box
        position="absolute"
        bottom="10%"
        right="30%"
        w="90px"
        h="90px"
        bgGradient="radial(circle, rgba(139, 108, 47, 0.09), transparent)"
        filter="blur(7px)"
        borderRadius="50%"
        zIndex={0}
      />
      <Box
        position="absolute"
        top="70%"
        left="5%"
        w="70px"
        h="70px"
        bgGradient="radial(circle, rgba(201, 161, 74, 0.11), transparent)"
        filter="blur(5px)"
        borderRadius="50%"
        zIndex={0}
      />

      <Container maxW="6xl" pt={{ base: 10, md: 14 }} position="relative" zIndex={1}>
        <VStack spacing={{ base: 8, md: 12 }} align="stretch">
          <Stack spacing={2} textAlign={{ base: "left", md: "center" }}>
            <HStack justify={{ base: "flex-start", md: "center" }} spacing={3}>
              <EditIcon color="brand.goldDeep" fontSize={{ base: "2xl", md: "4xl" }} />
              <Heading fontSize={{ base: "2xl", md: "4xl" }}>AI解説生成システム</Heading>
            </HStack>
            <Text color="brand.muted" fontSize={{ base: "sm", md: "md" }}>
              過去問PDFから、AIが解答・解説PDFを作成します。
            </Text>
          </Stack>

          <Box
            bg="whiteAlpha.900"
            border="1px solid"
            borderColor="brand.gold"
            borderRadius="2xl"
            boxShadow="0 20px 40px rgba(34, 21, 8, 0.08)"
            p={{ base: 6, md: 8 }}
          >
            <Grid templateColumns={{ base: "1fr", lg: "1.2fr 0.8fr" }} gap={8}>
              <GridItem>
                <VStack spacing={6} align="stretch">
                  <Box>
                    <Heading size="md" mb={2}>
                      新しいリクエスト
                    </Heading>
                    <Text color="brand.muted" fontSize="sm">
                      生成AIは誤答や不足が含まれる可能性があります。最終判断は必ず担当者が行ってください。
                    </Text>
                  </Box>

                  <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                    <FormControl>
                      <FormLabel>APIキー（任意）</FormLabel>
                      <Input
                        value={apiKey}
                        onChange={(event) => setApiKey(event.target.value)}
                        placeholder="Gemini API Key"
                        type="password"
                        autoComplete="new-password"
                        focusBorderColor="brand.gold"
                      />
                    </FormControl>
                    <FormControl>
                      <FormLabel>年度</FormLabel>
                      <Input
                        value={year}
                        onChange={(event) =>
                          setYear(event.target.value.replace(/\D/g, "").slice(0, 4))
                        }
                        placeholder="2024"
                        inputMode="numeric"
                        pattern="\\d{1,4}"
                        maxLength={4}
                        focusBorderColor="brand.gold"
                      />
                      <Text fontSize="xs" color="brand.muted" mt={1}>
                        1〜4桁の数字
                      </Text>
                    </FormControl>
                    <FormControl>
                      <FormLabel>試験科目名</FormLabel>
                      <Input
                        value={subject}
                        onChange={(event) => setSubject(event.target.value)}
                        placeholder="生化学"
                        maxLength={MAX_TEXT_LENGTH}
                        focusBorderColor="brand.gold"
                      />
                      <Text
                        fontSize="xs"
                        color={subject.length >= MAX_TEXT_LENGTH ? "red.600" : "brand.muted"}
                        mt={1}
                      >
                        {subject.length}/{MAX_TEXT_LENGTH}
                      </Text>
                    </FormControl>
                    <FormControl>
                      <FormLabel>大学名</FormLabel>
                      <Input
                        value={university}
                        onChange={(event) => setUniversity(event.target.value)}
                        placeholder="東京大学"
                        maxLength={MAX_TEXT_LENGTH}
                        focusBorderColor="brand.gold"
                      />
                      <Text
                        fontSize="xs"
                        color={university.length >= MAX_TEXT_LENGTH ? "red.600" : "brand.muted"}
                        mt={1}
                      >
                        {university.length}/{MAX_TEXT_LENGTH}
                      </Text>
                    </FormControl>
                    <FormControl>
                      <FormLabel>試験問題作者名</FormLabel>
                      <Input
                        value={author}
                        onChange={(event) => setAuthor(event.target.value)}
                        placeholder="佐藤先生"
                        maxLength={MAX_TEXT_LENGTH}
                        focusBorderColor="brand.gold"
                      />
                      <Text
                        fontSize="xs"
                        color={author.length >= MAX_TEXT_LENGTH ? "red.600" : "brand.muted"}
                        mt={1}
                      >
                        {author.length}/{MAX_TEXT_LENGTH}
                      </Text>
                    </FormControl>
                    <FormControl>
                      <FormLabel>解説タイトル</FormLabel>
                      <Input
                        value={explanationName}
                        onChange={(event) => {
                          setExplanationName(event.target.value);
                          setUserEditedName(true);
                        }}
                        placeholder="2024_生化学_解答解説"
                        maxLength={MAX_TEXT_LENGTH}
                        focusBorderColor="brand.gold"
                      />
                      <Text
                        fontSize="xs"
                        color={explanationName.length >= MAX_TEXT_LENGTH ? "red.600" : "brand.muted"}
                        mt={1}
                      >
                        {explanationName.length}/{MAX_TEXT_LENGTH}
                      </Text>
                    </FormControl>
                  </SimpleGrid>

                  <FormControl>
                    <FormLabel>問題ファイル（PDF）</FormLabel>
                    <Box
                      position="relative"
                      border="1px dashed"
                      borderColor="brand.gold"
                      borderRadius="xl"
                      bg="brand.bg"
                      p={4}
                      textAlign="center"
                      cursor="pointer"
                      _hover={{ bg: "rgba(201, 161, 74, 0.08)" }}
                    >
                      <VStack spacing={1} pointerEvents="none">
                        <AttachmentIcon color="brand.goldDeep" />
                        <Text fontSize="sm" color="brand.ink">
                          クリックしてPDFを選択
                        </Text>
                        <Text fontSize="xs" color="brand.muted">
                          {inputFile ? inputFile.name : "未選択"}
                        </Text>
                      </VStack>
                      <Input
                        type="file"
                        accept="application/pdf"
                        onChange={(event) => handleFileChange(event, setInputFile)}
                        focusBorderColor="brand.gold"
                        position="absolute"
                        inset={0}
                        opacity={0}
                        w="100%"
                        h="100%"
                        m={0}
                        cursor="pointer"
                      />
                    </Box>
                  </FormControl>

                  <HStack spacing={4} align="center" flexWrap="wrap">
                    <Button
                      colorScheme="yellow"
                      bg="brand.gold"
                      color="brand.ink"
                      _hover={{ bg: "brand.goldDeep", color: "white" }}
                      onClick={onSubmit}
                      isDisabled={!canSubmit}
                      leftIcon={<ArrowForwardIcon />}
                    >
                      リクエストする
                    </Button>
                  </HStack>
                </VStack>
              </GridItem>

              <GridItem>
                <VStack spacing={4} align="stretch">
                  <Heading size="sm">補足</Heading>
                  <Box>
                    <Text fontSize="sm" color="brand.muted" mb={2}>
                      現在のジョブはブラウザに保存されます。別端末からは見えません。
                    </Text>
                    <Text fontSize="xs" color="brand.muted">
                      進行中のジョブのみ自動で更新します。
                    </Text>
                  </Box>
                </VStack>
              </GridItem>
            </Grid>
          </Box>

          <Box>
            <HStack justify="space-between" mb={4} flexWrap="wrap">
              <Heading size="md">ジョブ一覧</Heading>
              <Button
                size="sm"
                variant="outline"
                borderColor="brand.gold"
                color="brand.ink"
                _hover={{ bg: "brand.gold", color: "brand.ink" }}
                onClick={handleRefreshClick}
                isDisabled={pendingJobs.length === 0 || isRefreshing || isRefreshCooldown}
                isLoading={isRefreshing || isRefreshCooldown}
                leftIcon={<RepeatIcon />}
              >
                更新する
              </Button>
            </HStack>
            {jobs.length === 0 ? (
              <Box
                border="1px dashed"
                borderColor="brand.gold"
                borderRadius="xl"
                p={6}
                textAlign="center"
                color="brand.muted"
              >
                まだジョブがありません。上のフォームから解答解説作成ジョブを依頼してみよう！
              </Box>
            ) : (
              <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={5}>
                {jobs.map((job) => {
                  const label = statusLabels[job.status] ?? job.status;
                  const badgeStyle = statusBadgeStyles[job.status] ?? {
                    bg: "#EFE7DA",
                    color: "#6D5F4B"
                  };
                  const etaLabel = etaLabels[job.status];
                  const createdAtMs = new Date(job.createdAt).getTime();
                  const isStalled =
                    job.status === "generating_md" &&
                    Number.isFinite(createdAtMs) &&
                    Date.now() - createdAtMs >= 30 * 60 * 1000;
                  const isDownloadable = job.status === "done";
                  const isRetryable = job.status === "failed_to_convert" || isStalled;
                  const isDownloading = downloadingJobId === job.jobId;

                  return (
                    <Box
                      key={job.jobId}
                      position="relative"
                      bg="white"
                      border="1px solid"
                      borderColor="brand.gold"
                      borderRadius="xl"
                      p={5}
                      boxShadow="0 12px 24px rgba(28, 18, 7, 0.08)"
                    >
                      {isDownloading ? (
                        <Box
                          position="absolute"
                          inset={0}
                          bg="rgba(247, 244, 238, 0.72)"
                          borderRadius="xl"
                          display="flex"
                          alignItems="center"
                          justifyContent="center"
                          flexDirection="column"
                          gap={4}
                          zIndex={1}
                        >
                          <Text fontSize="sm" color="brand.ink">
                            ダウンロード中...
                          </Text>
                          <Box
                            position="relative"
                            w="70%"
                            h="6px"
                            bg="rgba(201, 161, 74, 0.2)"
                            borderRadius="999px"
                            overflow="hidden"
                          >
                            <Box
                              position="absolute"
                              top={0}
                              left={0}
                              w="100%"
                              h="100%"
                              bg="brand.gold"
                              transformOrigin="left"
                              animation={`${loadingBar} 2.2s ease-in-out infinite`}
                            />
                          </Box>
                          <Box
                            w="22px"
                            h="22px"
                            bg="brand.goldDeep"
                            animation={`${shapeShift} 2.6s ease-in-out infinite`}
                          />
                        </Box>
                      ) : null}

                      <VStack spacing={3} align="stretch" opacity={isDownloading ? 0.4 : 1}>
                        <HStack justify="space-between" flexWrap="wrap">
                          <Text fontWeight="600">{job.explanationName}</Text>
                          <HStack spacing={2} align="center">
                            <Badge bg={badgeStyle.bg} color={badgeStyle.color} borderRadius="full" px={3}>
                              {label}
                            </Badge>
                            {etaLabel ? (
                              <Text fontSize="xs" color="brand.muted">
                                {etaLabel}
                              </Text>
                            ) : null}
                          </HStack>
                        </HStack>
                        <Text fontSize="sm" color="brand.muted">
                          job_id: {job.jobId}
                        </Text>
                        <Text fontSize="xs" color="brand.muted">
                          作成: {formatDate(job.createdAt)} / 更新: {formatDate(job.updatedAt)}
                        </Text>
                        {job.message ? (
                          <Text fontSize="sm" color="brand.muted">
                            {job.message}
                          </Text>
                        ) : null}
                        {job.error ? (
                          <Text fontSize="sm" color="red.700">
                            {job.error}
                          </Text>
                        ) : null}
                        <HStack spacing={3} flexWrap="wrap">
                          {isDownloadable ? (
                            <Button
                              alignSelf="flex-start"
                              size="sm"
                              bg="brand.gold"
                              color="brand.ink"
                              _hover={{ bg: "brand.goldDeep", color: "white" }}
                              onClick={() => handleDownload(job.jobId)}
                              leftIcon={<DownloadIcon />}
                            >
                              ダウンロードする
                            </Button>
                          ) : null}
                          {isRetryable ? (
                            <>
                              <Text fontSize="xs" color="brand.muted">
                                エラーが発生したかも？
                              </Text>
                              <Button
                                alignSelf="flex-start"
                                size="sm"
                                variant="outline"
                                borderColor="brand.gold"
                                color="brand.ink"
                                _hover={{ bg: "brand.gold", color: "brand.ink" }}
                                onClick={() => openRetryModal(job)}
                              >
                                もう一度試す
                              </Button>
                            </>
                          ) : null}
                        </HStack>
                      </VStack>
                    </Box>
                  );
                })}
              </SimpleGrid>
            )}
          </Box>

          <Box
            bg="whiteAlpha.900"
            border="1px solid"
            borderColor="brand.gold"
            borderRadius="xl"
            p={{ base: 4, md: 5 }}
          >
            <HStack justify="space-between" mb={3} flexWrap="wrap">
              <Heading size="sm">ジョブを追加</Heading>
              <Badge bg="brand.bg" color="brand.muted" borderRadius="full" px={3}>
                ＋ 追加
              </Badge>
            </HStack>
            <Text fontSize="sm" color="brand.muted" mb={3}>
              job_id を入力すると、ジョブ一覧に追加してステータスを確認します。
            </Text>
            <HStack spacing={3} flexWrap="wrap">
              <Input
                value={searchJobId}
                onChange={(event) => setSearchJobId(event.target.value)}
                placeholder="「pipeline-」から始まるJOB_ID を入力"
                focusBorderColor="brand.gold"
              />
              <Button
                size="sm"
                bg="brand.gold"
                color="brand.ink"
                _hover={{ bg: "brand.goldDeep", color: "white" }}
                onClick={handleSearchJob}
                isDisabled={isSearching}
              >
                ＋ ジョブを検索して追加
              </Button>
            </HStack>
          </Box>
        </VStack>
      </Container>

      <Box as="footer" mt={{ base: 10, md: 14 }} pb={{ base: 6, md: 10 }}>
        <Container maxW="6xl" ml={4}>
          <VStack spacing={4} justify="center" align="center">
            <Text fontSize="sm" color="brand.muted">
              © 2026 Medteria igatatsu｜ All rights reserved.
            </Text>
          </VStack>
        </Container>
      </Box>

      <Modal isOpen={isRetryOpen} onClose={closeRetryModal} size="xl">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>もう一度試す</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack spacing={4} align="stretch">
              <Text fontSize="sm" color="brand.muted">
                前回の入力をできるだけ引き継いでいます。必要な箇所だけ修正してください。
              </Text>
              <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                <FormControl>
                  <FormLabel>APIキー（任意）</FormLabel>
                  <Input
                    value={retryApiKey}
                    onChange={(event) => setRetryApiKey(event.target.value)}
                    placeholder="Gemini API Key"
                    focusBorderColor="brand.gold"
                    type="password"
                    autoComplete="new-password"
                  />
                </FormControl>
                <FormControl>
                  <FormLabel>年度</FormLabel>
                  <Input
                    value={retryYear}
                    onChange={(event) =>
                      setRetryYear(event.target.value.replace(/\D/g, "").slice(0, 4))
                    }
                    placeholder="2024"
                    inputMode="numeric"
                    pattern="\\d{1,4}"
                    maxLength={4}
                    focusBorderColor="brand.gold"
                  />
                  <Text fontSize="xs" color="brand.muted" mt={1}>
                    1〜4桁の数字
                  </Text>
                </FormControl>
                <FormControl>
                  <FormLabel>試験科目名</FormLabel>
                  <Input
                    value={retrySubject}
                    onChange={(event) => setRetrySubject(event.target.value)}
                    placeholder="生化学"
                    maxLength={MAX_TEXT_LENGTH}
                    focusBorderColor="brand.gold"
                  />
                  <Text
                    fontSize="xs"
                    color={retrySubject.length >= MAX_TEXT_LENGTH ? "red.600" : "brand.muted"}
                    mt={1}
                  >
                    {retrySubject.length}/{MAX_TEXT_LENGTH}
                  </Text>
                </FormControl>
                <FormControl>
                  <FormLabel>大学名</FormLabel>
                  <Input
                    value={retryUniversity}
                    onChange={(event) => setRetryUniversity(event.target.value)}
                    placeholder="東京大学"
                    maxLength={MAX_TEXT_LENGTH}
                    focusBorderColor="brand.gold"
                  />
                  <Text
                    fontSize="xs"
                    color={retryUniversity.length >= MAX_TEXT_LENGTH ? "red.600" : "brand.muted"}
                    mt={1}
                  >
                    {retryUniversity.length}/{MAX_TEXT_LENGTH}
                  </Text>
                </FormControl>
                <FormControl>
                  <FormLabel>試験問題作者名</FormLabel>
                  <Input
                    value={retryAuthor}
                    onChange={(event) => setRetryAuthor(event.target.value)}
                    placeholder="佐藤先生"
                    maxLength={MAX_TEXT_LENGTH}
                    focusBorderColor="brand.gold"
                  />
                  <Text
                    fontSize="xs"
                    color={retryAuthor.length >= MAX_TEXT_LENGTH ? "red.600" : "brand.muted"}
                    mt={1}
                  >
                    {retryAuthor.length}/{MAX_TEXT_LENGTH}
                  </Text>
                </FormControl>
                <FormControl>
                  <FormLabel>解説タイトル</FormLabel>
                  <Input
                    value={retryExplanationName}
                    onChange={(event) => {
                      setRetryExplanationName(event.target.value);
                      setRetryUserEditedName(true);
                    }}
                    placeholder="2024_生化学_解答解説"
                    maxLength={MAX_TEXT_LENGTH}
                    focusBorderColor="brand.gold"
                  />
                  <Text
                    fontSize="xs"
                    color={
                      retryExplanationName.length >= MAX_TEXT_LENGTH ? "red.600" : "brand.muted"
                    }
                    mt={1}
                  >
                    {retryExplanationName.length}/{MAX_TEXT_LENGTH}
                  </Text>
                </FormControl>
              </SimpleGrid>
              <FormControl>
                <FormLabel>問題ファイル（PDF）</FormLabel>
                <Box
                  position="relative"
                  border="1px dashed"
                  borderColor="brand.gold"
                  borderRadius="xl"
                  bg="brand.bg"
                  p={4}
                  textAlign="center"
                  cursor="pointer"
                  _hover={{ bg: "rgba(201, 161, 74, 0.08)" }}
                >
                  <VStack spacing={1} pointerEvents="none">
                    <AttachmentIcon color="brand.goldDeep" />
                    <Text fontSize="sm" color="brand.ink">
                      クリックしてPDFを選択
                    </Text>
                    <Text fontSize="xs" color="brand.muted">
                      {retryFile ? retryFile.name : "未選択"}
                    </Text>
                  </VStack>
                  <Input
                    type="file"
                    accept="application/pdf"
                    onChange={(event) => handleFileChange(event, setRetryFile)}
                    focusBorderColor="brand.gold"
                    position="absolute"
                    inset={0}
                    opacity={0}
                    w="100%"
                    h="100%"
                    m={0}
                    cursor="pointer"
                  />
                </Box>
              </FormControl>
              {retryJob ? (
                <Text fontSize="xs" color="brand.muted">
                  対象ジョブ: {retryJob.jobId}
                </Text>
              ) : null}
            </VStack>
          </ModalBody>
          <ModalFooter>
            <HStack spacing={3}>
              <Button variant="ghost" onClick={closeRetryModal}>
                閉じる
              </Button>
              <Button
                bg="brand.gold"
                color="brand.ink"
                _hover={{ bg: "brand.goldDeep", color: "white" }}
                onClick={onRetrySubmit}
                isDisabled={!retryCanSubmit}
              >
                もう一度試す
              </Button>
            </HStack>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <Modal isOpen={isNoticeOpen} onClose={closeNoticeModal} size="lg">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>リクエスト受付後のご案内</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack spacing={4} align="stretch">
              <Box display="flex" justifyContent="center">
                <Box
                  w="56px"
                  h="56px"
                  borderRadius="full"
                  bg="brand.bg"
                  display="flex"
                  alignItems="center"
                  justifyContent="center"
                  animation={`${noticeCheck} 0.8s ease-out`}
                >
                  <CheckIcon w="30px" h="30px" color="brand.goldDeep" />
                </Box>
              </Box>
              <Text fontSize="sm" color="brand.muted">
                最大15〜20分程度の待ち時間が発生する場合があります。
              </Text>
              <Text fontSize="sm" color="brand.muted">
                リクエスト情報は端末ブラウザ内に保存されるため、待ち時間中は自由に退出してかまいません。
              </Text>
              <Text fontSize="sm" color="brand.muted">
                必要であれば job_id を控えておくと、後で検索できます。
              </Text>
              {noticeJobId ? (
                <HStack spacing={3} flexWrap="wrap">
                  <Badge bg="brand.bg" color="brand.muted" borderRadius="full" px={3}>
                    job_id
                  </Badge>
                  <Text fontSize="sm" color="brand.ink">
                    {noticeJobId}
                  </Text>
                  <Button
                    size="xs"
                    variant="outline"
                    borderColor="brand.gold"
                    color="brand.ink"
                    _hover={{ bg: "brand.gold", color: "brand.ink" }}
                    onClick={handleCopyJobId}
                    leftIcon={<CopyIcon />}
                  >
                    コピー
                  </Button>
                </HStack>
              ) : null}
              <Text fontSize="sm" color="brand.muted">
                サイズが大きい場合や混雑時には、生成に失敗する可能性があります。
              </Text>
              <Text fontSize="sm" color="brand.muted">
                節度を守った利用をお願いします。
              </Text>
            </VStack>
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" onClick={closeNoticeModal}>
              閉じる
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  );
}
